from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256

import pytest

from offline_cases import RUN, implementation


def edition(start, data, name):
    return {"from_day": start, "body": data, "url": "https://rates.example.org/" + name,
            "sha256": sha256(data).hexdigest()}


PRICE = edition("2032-03-01", b'{"plans_metal":[{"id":"sample","hourly_cost":1.25}]}', "price")
OLD = edition("2032-03-01", b'{"base":"USD","quote":"EUR","n":2,"d":3}', "fx-a")
NEW = edition("2032-03-02", b'{"base":"USD","quote":"EUR","n":5,"d":7}', "fx-b")
FUTURE = edition("2032-03-03", b'{"base":"USD","quote":"EUR","n":9,"d":10}', "fx-c")
LINES = [{"sku": "sample", "currency": "USD", "quantity": 2, "billed_periods": 3, "setup_price_micros": 125000}]
TIMES = ("2032-03-02T00:59:59+01:00", "2032-03-02T01:00:00+01:00")


def test_effective_currency_reference():
    from rezono_compiler import batch, pack, rules

    assert [datetime.fromisoformat(t).astimezone(timezone.utc).day for t in TIMES] == [1, 2]
    total = 2 * (3 * Fraction("1.25") + Fraction("0.125"))
    assert (total, total * Fraction(2, 3), total * Fraction(5, 7)) == (
        Fraction(31, 4), Fraction(31, 6), Fraction(155, 28))
    program = rules.load(pack.read(RUN.parent / "packs/std-time").rules)
    facts = {"interval__on_axis": [(x, "day") for x in ("old", "new", "future")],
             "interval__start": [("old", 1), ("new", 2), ("future", 3)],
             "interval__end": [("old", 2), ("new", 3)], "interval__unbounded": [("future", "end")],
             "reference_point__on_axis": [("q1", "day"), ("q2", "day"), ("q9", "day")],
             "reference_point__position": [("q1", 1), ("q2", 2), ("q9", 9)]}
    db = batch.connect(program, facts)
    try:
        batch.compute(db, program)
        assert batch.read(db, program, ["holds_at"])["holds_at"] == {("old", "q1"), ("new", "q2"), ("future", "q9")}
    finally:
        db.close()


def test_effective_currency():
    quote = implementation("effective_quote.py", "quote_at")
    rates = [FUTURE, OLD, NEW]
    for stamp, rate, eur in [(TIMES[0], OLD, [31, 6]), (TIMES[1], NEW, [155, 28]),
                             ("2032-04-01T00:00:00Z", FUTURE, [279, 40])]:
        result = quote(stamp, LINES, [PRICE], rates)
        assert result == {"usd": [31, 4], "eur": eur, "price_source": PRICE["sha256"],
                          "fx_source": rate["sha256"], "problems": []}
    for prices, fx, reason in [([], rates, "missing_price"), ([PRICE], [FUTURE], "missing_fx"),
                               ([PRICE, dict(PRICE, url="https://rates.example.org/rival")], rates, "ambiguous_price"),
                               ([PRICE], [OLD, NEW, dict(FUTURE, from_day=NEW["from_day"])], "ambiguous_fx")]:
        assert quote(TIMES[1], LINES, prices, fx) == {"problems": [reason]}
    with pytest.raises(ValueError):
        quote(TIMES[1], LINES, [PRICE], [dict(NEW, body=OLD["body"])])


@pytest.mark.parametrize("first, second", [(2, 3), (3, 2)])
def test_quote_rejects_duplicate_fx_members(first, second):
    quote = implementation("effective_quote.py", "quote_at")
    raw = f'{{"base":"USD","quote":"EUR","n":{first},"n":{second},"d":4}}'.encode("utf-8")
    rate = edition("2032-03-01", raw, "duplicate-rate")
    with pytest.raises(ValueError, match="duplicate rate capture field 'n'"):
        quote(TIMES[0], LINES, [PRICE], [rate])


def test_quote_keeps_the_exact_ratio_and_source_digests():
    quote = implementation("effective_quote.py", "quote_at")
    rate = edition("2032-03-01", b'{"base":"USD","quote":"EUR","n":2,"d":4}', "bounded-rate")
    result = quote(TIMES[0], LINES, [PRICE], [rate])
    usd = 2 * (3 * Fraction("1.25") + Fraction("0.125"))
    assert Fraction(*result["usd"]) == usd
    assert Fraction(*result["eur"]) == usd * Fraction(2, 4)
    assert result["price_source"] == sha256(PRICE["body"]).hexdigest()
    assert result["fx_source"] == sha256(rate["body"]).hexdigest()
    assert result["problems"] == []
