from fractions import Fraction
from hashlib import sha256

import pytest

from offline_cases import implementation


def test_exact_quote():
    quote = implementation("exact_quote.py", "total_micros")
    def line(count, periods, price, setup=0, currency="USD"):
        return dict(quantity=count, billed_periods=periods, period_price_micros=price,
                    setup_price_micros=setup, currency=currency)
    independent = 2 * (2 * Fraction("0.164") + Fraction("0.479")) * 1_000_000
    assert quote([line(2, 2, 164000), line(1, 2, 479000)], "USD") == independent == 1614000
    assert quote([line(2, 3, 1, 7)], "USD") == 20
    assert quote([], "USD") == 0
    for bad in (line(-1, 2, 1), line(True, 2, 1), line(1, 2, 0.5), line(1, 2, 1, currency="EUR")):
        with pytest.raises(ValueError):
            quote([bad], "USD")


def test_quote_preserves_arbitrary_width_and_identical_lines(monkeypatch):
    from run import exact_quote

    wide = 2**63
    cases = [
        (wide + 1, wide + 3, wide + 5, wide + 7),
        (2**15 + 1, 2**10 + 3, 2**10 + 5, 7),
        (2**7 + 1, 2**17 + 3, 2**16 + 5, 7),
    ]

    def compare(values):
        quantity, periods, rate, setup = values
        line = dict(quantity=quantity, billed_periods=periods, period_price_micros=rate,
                    setup_price_micros=setup, currency="USD")
        oracle = 2 * Fraction(quantity) * (Fraction(periods) * Fraction(rate) + Fraction(setup))
        assert exact_quote.total_micros(iter([line, line]), "USD") == oracle

    compare(cases[0])
    # Exercise both kinds of slicing at a test-size column limit.
    monkeypatch.setattr(exact_quote, "COLUMN_LIMIT", 70_000)
    for case in cases[1:]:
        compare(case)


def test_quote_line_and_total_witnesses_pass_the_independent_checker():
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations, load_rules
    from rezono_compiler import batch, explain

    from run.exact_quote import _Line, _valued_quote

    rate = 2**63 + 19
    line = _Line(2, 3, rate, 7)
    with _valued_quote([line, line]) as (model, program, connection):
        rows = batch.read(connection, program, sorted(program.relations))
        explainer = explain.Explainer(program, rows, batch.witnesses(connection, program))
        witnesses = explainer.chosen()
        sources = {name: explainer.snapshot(name).encode("utf-8") for name in rows}

    expected_line = 2 * (3 * Fraction(rate) + 7)
    for ref, expected in (("line/0", expected_line), ("line/1", expected_line), ("quote", 2 * expected_line)):
        digits = {int(position): int(digit) for amount, position, digit in rows["amount_digit"] if amount == ref}
        assert digits and sum(digit * 10**position for position, digit in digits.items()) == expected

    manifest = {"id": "synthetic-quote", "snapshots": [
        {"relation": name, "role": "all", "complete": True, "uri": name, "format": "json",
         "sha256": sha256(raw).hexdigest()}
        for name, raw in sources.items()
    ]}
    rule_ir = load_rules(model.rules)
    derived = derived_relations(model.rules, rule_ir)
    assert check_epoch(witnesses, manifest, rule_ir, sources.__getitem__, derived=derived)["valid"]
    missing_total = [w for w in witnesses if w["conclusion"]["key"] != '["quote","0","2"]'
                     or w["conclusion"]["relation"] != "amount_digit"]
    report = check_epoch(missing_total, manifest, rule_ir, sources.__getitem__, derived=derived)
    assert not report["valid"]
    assert "unproven_row" in {finding["reason"] for finding in report["findings"]}
