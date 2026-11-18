"""Check invoice rounding against independent amounts and the ordinary proof checker."""

import json
from contextlib import closing
from hashlib import sha256

import pytest

from offline_cases import RUN, implementation
from test_invoice_evidence import cost, invoice, terms


def test_invoice_rounding_retains_the_distinct_full_price_sources():
    from rezono_checker.check import check, check_epoch
    from rezono_checker.rules import derived_relations, load_rules
    from rezono_compiler import batch, explain, pack, rules

    normalize = implementation("invoice_compare.py", "invoice_facts")
    model = pack.read(RUN / "packs" / "invoice-drift")
    program = rules.load(model.rules)
    verifier = load_rules(model.rules)
    prices = [cost("tie", [5, 8]), cost("exact", [63, 100])]
    observed = [invoice("tie", 64, "invoice/1"), invoice("exact", 64, "invoice/2")]
    with closing(batch.connect(program, normalize(prices, observed, terms("half_up")))) as con:
        batch.compute(con, program, witnesses=True)
        derived = batch.read(con, program)
        rows = batch.read(con, program, program.base_used()) | derived
        explainer = explain.Explainer(program, rows, batch.witnesses(con, program))
    assert {row[-2:] for row in derived["amount_difference"]} == {("63", "64")}
    snapshots = {name: explainer.snapshot(name).encode() for name in rows}
    manifest = {"id": "invoice-rounding", "snapshots": [
        {"relation": name, "role": "all", "complete": True, "format": "json", "uri": name,
         "sha256": sha256(body).hexdigest()} for name, body in snapshots.items()
    ]}
    epoch = check_epoch(
        explainer.chosen(), manifest, verifier, snapshots.__getitem__, derived=derived_relations(model.rules, verifier),
    )
    assert epoch["valid"], epoch["findings"][:5]

    def price_value(ref, part):
        positions = {rid: int(position) for rid, position in rows["rounding_digit__position"]}
        lines = dict(rows["rounding_digit__line"])
        parts = dict(rows["rounding_digit__part"])
        return sum(int(digit) * 10**positions[rid] for rid, digit in rows["rounding_digit__digit"]
                   if lines[rid] == ref and parts[rid] == part)

    assert [(price_value(ref, "numerator"), price_value(ref, "denominator"))
            for ref in ("cost/tie", "cost/exact")] == [(5, 8), (63, 100)]
    amount = next(row for row in derived["amount_difference"] if row[1] == "tie")
    proof = explainer.proof("amount_difference", amount, manifest["id"])
    report = check(proof, manifest, verifier, snapshots.__getitem__)
    assert report["valid"], report["findings"][:5]
    assert any(w["conclusion"]["relation"] == "checked_column" for w in proof["witnesses"])

    # Keep the old result and witness while replacing one recorded carry and
    # recomputing its snapshot digest. A valid digest does not prove the equation.
    relation = "rounding_carry__carry"
    original = json.loads(snapshots[relation])
    carry = next(row for row in original if row["key"][0] == "cost/tie/division/1")
    carry["key"][1] = str(int(carry["key"][1]) + 1)
    snapshots[relation] = json.dumps(original).encode()
    next(s for s in manifest["snapshots"] if s["relation"] == relation)["sha256"] = sha256(snapshots[relation]).hexdigest()
    assert not check(proof, manifest, verifier, snapshots.__getitem__)["valid"]


@pytest.mark.parametrize(("rounding", "expected"), [
    ("half_up", [63, 63, -63, -13, 100, 100, 0, -(2**63), 2**63 - 1]),
    ("half_even", [62, 63, -62, -12, 100, 100, 0, -(2**63), 2**63 - 1]),
])
def test_invoice_rounding_accepts_wide_rationals_and_signed_amounts(rounding, expected):
    from rezono_compiler import batch, pack, rules

    normalize = implementation("invoice_compare.py", "invoice_facts")
    amounts = [
        (5, 8), (63, 100), (-5, 8), (-1, 8),
        (2**63 + 1, 2**63 + 3), (2**63 - 1, 2**63 - 2), (1, 10**100),
        (-(2**63), 100), (2**63 - 1, 100),
    ]
    prices = [cost(f"item/{i}", pair) for i, pair in enumerate(amounts)]
    observed = [invoice(f"item/{i}", 1, f"invoice/{i}") for i in range(len(amounts))]
    program = rules.load(pack.read(RUN / "packs" / "invoice-drift").rules)
    with closing(batch.connect(program, normalize(prices, observed, terms(rounding)))) as con:
        batch.compute(con, program)
        actual = {row[1]: int(row[-2]) for row in batch.read(con, program, ["amount_difference"])["amount_difference"]}
    assert actual == {f"item/{i}": amount for i, amount in enumerate(expected)}


def test_invoice_rounding_requires_complete_and_correct_arithmetic():
    from rezono_compiler import batch, pack, rules

    normalize = implementation("invoice_compare.py", "invoice_facts")
    wrong = {
        "price": ("rounding_digit__digit", "numerator/0", "change"),
        "last": ("rounding_digit__last", "denominator/0", "delete"),
        "gap": ("rounding_digit__digit", "gap/0", "change"),
        "factor": ("rounding_word__remaining", "units/1", "delete"),
        "floor": ("rounding_word__remaining", "floor/0", "change"),
        "carry": ("rounding_carry__carry", "division/1", "delete"),
    }
    prices = [cost(item, [5, 8]) for item in ("intact", *wrong)]
    observed = [invoice(item, 64, f"invoice/{item}") for item in ("intact", *wrong)]
    data = normalize(prices, observed, terms("half_up"))
    for item, (relation, suffix, operation) in wrong.items():
        ref = f"cost/{item}/{suffix}"
        (row,) = [entry for entry in data[relation] if entry[0] == ref]
        data[relation].remove(row)
        if operation == "change":
            data[relation].append((ref, (row[1] + 1) if row[1] < 9 else row[1] - 1))
    program = rules.load(pack.read(RUN / "packs" / "invoice-drift").rules)
    with closing(batch.connect(program, data)) as con:
        batch.compute(con, program)
        outputs = batch.read(con, program, ["amount_difference"])["amount_difference"]
    assert {row[1] for row in outputs} == {"intact"}
