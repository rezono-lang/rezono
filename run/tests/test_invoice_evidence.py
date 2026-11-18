from fractions import Fraction
from hashlib import sha256

import pytest

from offline_cases import RUN, implementation, relation


PLAN = sha256(b"priced synthetic order").hexdigest()
OTHER = sha256(b"separate synthetic order").hexdigest()


def terms(mode):
    body = ('{"currency":"EUR","minor_per_unit":100,"boundary":"line","mode":"' + mode + '"}').encode()
    return {"url": "https://billing.example.org/terms", "sha256": sha256(body).hexdigest(), "body": body}


def cost(item, amount):
    return {"plan_hash": PLAN, "item": item, "currency": "EUR", "expected": amount, "ref": "cost/" + item}


def invoice(item, cents, ref, plan=PLAN):
    return {"plan_hash": plan, "item": item, "currency": "EUR", "observed_minor": cents, "ref": ref}


EXPECTED = [cost("rental", [5, 8]), cost("setup", [1, 8])]
MATCH = [invoice("rental", 63, "invoice/1"), invoice("setup", 13, "invoice/2")]
WRONG = [invoice("rental", 64, "invoice/1"), invoice("setup", 12, "invoice/2")]


def test_invoice_evidence_reference():
    exact = [100 * Fraction(*row["expected"]) for row in EXPECTED]
    half_up = [(2 * x.numerator + x.denominator) // (2 * x.denominator) for x in exact]
    assert half_up == [63, 13]
    assert [round(x) for x in exact] == [62, 12]
    observed = [row["observed_minor"] for row in WRONG]
    assert sum(half_up) == sum(observed) and [a - b for a, b in zip(observed, half_up)] == [1, -1]


def test_invoice_evidence():
    normalize = implementation("invoice_compare.py", "invoice_facts")

    def compare(observations, policy):
        facts = normalize(EXPECTED, observations, policy)
        return (relation("invoice-drift", facts, "amount_difference"),
                relation("invoice-drift", facts, "unbound_invoice"))

    up = terms("half_up")
    assert compare(MATCH, up) == (set(), set())
    orphans = [invoice("rental", 63, "invoice/3", None), invoice("extra", 1, "invoice/4"),
               invoice("rental", 63, "invoice/5", OTHER)]
    expected = {(PLAN, "rental", "cost/rental", "invoice/1", up["sha256"], "63", "64"),
                (PLAN, "setup", "cost/setup", "invoice/2", up["sha256"], "13", "12")}
    assert compare(WRONG + orphans, up) == (expected, {("invoice/3", "missing_plan"),
                                                       ("invoice/4", "unmatched_item"),
                                                       ("invoice/5", "unmatched_item")})
    even = terms("half_even")
    assert compare(MATCH, even) == (
        {(PLAN, "rental", "cost/rental", "invoice/1", even["sha256"], "62", "63"),
         (PLAN, "setup", "cost/setup", "invoice/2", even["sha256"], "12", "13")}, set())
    with pytest.raises(ValueError):
        normalize(EXPECTED, MATCH, dict(up, body=even["body"]))


@pytest.mark.parametrize("extra_minor", [63, -63])
def test_distinct_invoice_lines_cannot_share_one_priced_item(extra_minor):
    from rezono_checker import check
    from rezono_checker.rules import load_rules
    from rezono_compiler import batch, explain, pack, rules, trace

    normalize = implementation("invoice_compare.py", "invoice_facts")
    extra = invoice("rental", extra_minor, "invoice/3")
    observations = [*MATCH, extra, dict(extra)]
    rule_doc = pack.read(RUN / "packs" / "invoice-drift").rules
    program = rules.load(rule_doc)
    with batch.connect(program, normalize(EXPECTED, observations, terms("half_up"))) as con:
        batch.compute(con, program, witnesses=True)
        snapshots = batch.read(con, program, program.base_used()) | batch.read(con, program)
        explainer = explain.Explainer(program, snapshots, batch.witnesses(con, program))
        steps = trace.steps(program, explainer.chosen(), snapshots)

    assert snapshots["amount_difference"] == set()
    assert snapshots["unbound_invoice"] == {("invoice/1", "ambiguous_binding"), ("invoice/3", "ambiguous_binding")}
    documents = {name: explainer.snapshot(name).encode() for name in snapshots}
    manifest = {"id": "invoice-evidence", "snapshots": [
        {"relation": name, "role": "checker", "complete": True, "format": "json", "uri": name,
         "sha256": sha256(contents).hexdigest()}
        for name, contents in documents.items()
    ]}
    checked_rules = load_rules(rule_doc)
    for ref in ("invoice/1", "invoice/3"):
        key = (ref, "ambiguous_binding")
        root = ("unbound_invoice", explain.key_text(key))
        reached = trace.run(steps, [root], "back", "all", keep=["expected_line", "invoice_line"])
        assert reached - {root} == {("expected_line", explain.key_text(("cost/rental",))),
                                    ("invoice_line", explain.key_text(("invoice/1",))),
                                    ("invoice_line", explain.key_text(("invoice/3",)))}
        report = check(explainer.proof("unbound_invoice", key, manifest["id"]), manifest, checked_rules,
                       documents.__getitem__)
        assert report["valid"], report["findings"]


def test_invoice_retries_and_different_scopes_do_not_make_a_binding_ambiguous():
    normalize = implementation("invoice_compare.py", "invoice_facts")
    observations = [
        *MATCH, dict(MATCH[0]),
        invoice("rental", 63, "invoice/other-plan", OTHER),
        dict(invoice("rental", 63, "invoice/other-currency"), currency="USD"),
    ]
    policy = terms("half_up")
    facts = normalize([*EXPECTED, dict(EXPECTED[0], plan_hash=OTHER, ref="cost/other-plan")], observations, policy)
    assert relation("invoice-drift", facts, "unbound_invoice") == {("invoice/other-currency", "unmatched_item")}
    assert relation("invoice-drift", facts, "amount_difference") == set()
