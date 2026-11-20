"""The converted amount of a quote is an exact-quote row: decisions/code-does-not-decide.md.

The expectation is the behaviour of run/effective_quote.py under decisions/run-effective-currency.md, whose
answers stay as they are; only the place of the conversion changes.
"""
from hashlib import sha256

import pytest

from offline_cases import implementation


def edition(start, data, name):
    return {"from_day": start, "body": data, "url": "https://rates.example.org/" + name,
            "sha256": sha256(data).hexdigest()}


PRICE = edition("2032-03-01", b'{"plans_metal":[{"id":"sample","hourly_cost":1.25}]}', "price")
OLD = edition("2032-03-01", b'{"base":"USD","quote":"EUR","n":2,"d":3}', "fx-a")
NEW = edition("2032-03-02", b'{"base":"USD","quote":"EUR","n":5,"d":7}', "fx-b")
FUTURE = edition("2032-03-03", b'{"base":"USD","quote":"EUR","n":9,"d":10}', "fx-c")
LINES = [{"sku": "sample", "currency": "USD", "quantity": 2, "billed_periods": 3, "setup_price_micros": 125000}]


def pack_reads(monkeypatch):
    """The (pack, relation) pairs whose derived rows the code reads."""
    from rezono_compiler import batch

    seen = set()
    read = batch.read

    def spy(con, prog, names=None):
        rows = read(con, prog, names)
        seen.update((prog.pack, name) for name in rows)
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return seen


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md, row run/effective_quote.py. Derive "
        "effective_amount(quote, currency, numerator, denominator) in run/packs/exact-quote from the quote total "
        "and the selected rate capture, exactly and without machine-word overflow, as the pack's digit columns "
        "already do for the total; which pair a capture converts is a pack fact (section 3), not a literal. "
        "run/effective_quote.py keeps quote_at as the reader: it selects the effective editions through std-time "
        "as today, reads effective_amount through rezono_compiler.batch.read and publishes reduced pairs. Keep "
        "run/tests/test_effective_currency.py green. Today line 126 multiplies in Python (AssertionError)."
    ),
)
def test_effective_amount_comes_from_the_quote_pack(monkeypatch):
    seen = pack_reads(monkeypatch)
    quote = implementation("effective_quote.py", "quote_at")
    rates = [FUTURE, OLD, NEW]
    for stamp, rate, eur in [("2032-03-02T00:59:59+01:00", OLD, [31, 6]), ("2032-03-02T01:00:00+01:00", NEW, [155, 28]),
                             ("2032-04-01T00:00:00Z", FUTURE, [279, 40])]:
        assert quote(stamp, LINES, [PRICE], rates) == {"usd": [31, 4], "eur": eur, "price_source": PRICE["sha256"],
                                                       "fx_source": rate["sha256"], "problems": []}
    assert ("exact-quote", "effective_amount") in seen, sorted(seen)
