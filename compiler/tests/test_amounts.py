"""RV-C20 on the minimal, domain-free fixture pack: the bundle says once per rule what each aggregate folds, as
the rule IR does, and a column of a derived relation carries a currency where the rules determine it."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE
from rede_compiler import emit, pack


@pytest.fixture
def fixture(tmp_path) -> Path:
    """The fixture with two amounts in different currencies and a plain number on Alpha."""
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    f = d / "schema" / "minimal.yaml"
    s = yaml.safe_load(f.read_text(encoding="utf-8"))
    s["classes"]["Alpha"]["attributes"]["size"]["annotations"] = {"currency": "EUR"}
    s["classes"]["Alpha"]["attributes"]["fee"] = {"range": "integer", "annotations": {"currency": "USD"}}
    s["classes"]["Alpha"]["attributes"]["rank"] = {"range": "integer"}
    f.write_text(yaml.safe_dump(s, sort_keys=False), encoding="utf-8", newline="\n")
    return d


def compiled(d: Path, text: str) -> tuple[dict, dict]:
    (d / "rules").mkdir(exist_ok=True)
    (d / "rules" / "core.dl").write_text(text, encoding="utf-8", newline="\n")
    files = emit.compile_pack(pack.read(d))
    assert files == emit.compile_pack(pack.read(d))   # the same input gives the same bytes
    return json.loads(files["bundle/schema-bundle.json"]), json.loads(files["ir/rules.json"])


def currencies(bundle: dict) -> dict:
    return {r["id"]: [c.get("currency") for c in r["columns"]] for r in bundle["relations"]}


AGGREGATES = """
.decl owned(a: symbol, b: symbol)
owned(a, b) :- beta__alpha(b, a).

.decl sizes(n: number, t: number)
sizes(n, t) :- n = count : { alpha__size(_, _) }, t = sum s : { alpha__size(_, s) }.

.decl least(a: symbol, m: number)
least(a, m) :- alpha(a), m = min s : { alpha__size(a, s) }.

.decl most(m: number)
most(m) :- m = max s : { alpha__size(_, s) }.

.decl owners(a: symbol, n: number)
owners(a, n) :- alpha(a), n = count : { owned(a, _) }.
"""


def test_a_rule_says_once_what_each_aggregate_folds_as_the_rule_ir_does(fixture):
    bundle, rules = compiled(fixture, AGGREGATES)
    got = {r["id"]: r.get("aggregates") for r in bundle["rules"]}
    assert got == {
        "owned": None,   # a rule without aggregates has no such field
        "sizes": [{"position": 0, "relation": "alpha__size", "function": "count"},
                  {"position": 1, "relation": "alpha__size", "function": "sum", "over": "v"}],
        "least": [{"position": 0, "relation": "alpha__size", "function": "min", "over": "v"}],
        "most": [{"position": 0, "relation": "alpha__size", "function": "max", "over": "v"}],
        "owners": [{"position": 0, "relation": "owned", "function": "count"}],
    }
    # the same words as the rule IR, which the checker reads, at the same positions
    for rule in rules["rules"]:
        want = [{k: a[k] for k in ("relation", "function", "over") if k in a} | {"position": i}
                for i, a in enumerate(rule.get("aggregates", []))]
        assert (got[rule["id"]] or []) == want, rule["id"]


AMOUNTS = """
// bound to an amount attribute, and to its bound
.decl priced(a: symbol, s: number)
priced(a, s) :- alpha__size(a, s), alpha__size__maximum(m), s <= m.

// a sum, a minimum and a maximum over an amount column are amounts; a count is a plain number
.decl folded(a: symbol, t: number, lo: number, hi: number, n: number)
folded(a, t, lo, hi, n) :- alpha(a), t = sum s : { priced(a, s) }, lo = min s : { priced(a, s) },
  hi = max s : { priced(a, s) }, n = count : { priced(a, _) }.

// a difference and a sum of amounts are amounts, also with 0, the one constant that is zero in every unit (P10.3);
// a product and a quotient are not
.decl spread(a: symbol, d: number, up: number, twice: number, half: number)
spread(a, d, up, twice, half) :- folded(a, _, lo, hi, _), d = hi - lo, up = hi + 0, twice = hi * 2, half = hi / 2.

// a constant in a head says nothing: the other rule decides
.decl owed(a: symbol, t: number)
owed(a, 0) :- alpha(a), !beta__alpha(a, a).
owed(a, t) :- folded(a, t, _, _, _).

// a plain number beside an amount in one column: the rules do not determine a currency
.decl mixed(a: symbol, x: number)
mixed(a, x) :- alpha__size(a, x).
mixed(a, x) :- alpha__rank(a, x).

// through recursion: every rule of the relation gives the amount
.decl reach(a: symbol, s: number)
reach(a, s) :- priced(a, s).
reach(b, s) :- reach(a, s), beta__alpha(b, a), alpha(b).

// another currency, on its own
.decl fees(a: symbol, f: number)
fees(a, f) :- alpha__fee(a, f).

.decl ranked(a: symbol, r: number)
ranked(a, r) :- alpha__rank(a, r).
"""


def test_a_column_has_the_currency_the_rules_determine(fixture):
    bundle, _ = compiled(fixture, AMOUNTS)
    assert currencies(bundle) == {
        "priced": [None, "EUR"],
        "folded": [None, "EUR", "EUR", "EUR", None],
        "spread": [None, "EUR", "EUR", None, None],
        "owed": [None, "EUR"],
        "mixed": [None, None],
        "reach": [None, "EUR"],
        "fees": [None, "USD"],
        "ranked": [None, None],
    }
    # a column without a currency has no such field
    assert next(r for r in bundle["relations"] if r["id"] == "ranked")["columns"] == [
        {"name": "a", "type": "string"}, {"name": "r", "type": "integer"}]


def test_without_an_amount_and_without_an_aggregate_the_bundle_says_neither():
    d = FIXTURE.parent / "minimal"
    model = pack.read(d)
    text = emit.compile_pack(model)["bundle/schema-bundle.json"]
    assert '"aggregates"' not in text
    assert all("currency" not in c for r in json.loads(text)["relations"] for c in r["columns"])


TWO_CURRENCIES = {
    "a-variable-in-two-columns": (
        ".decl same(a: symbol)\nsame(a) :- alpha__size(a, x), alpha__fee(a, x).\n",
        r"rules/core\.dl:2: x in same joins EUR and USD: two currencies in one variable"),
    "a-sum-of-two-amounts": (
        ".decl total(a: symbol, t: number)\ntotal(a, t) :- alpha__size(a, s), alpha__fee(a, f), t = s + f.\n",
        r"rules/core\.dl:2: t in total joins EUR and USD"),
    "two-rules-of-one-relation": (
        ".decl cost(a: symbol, c: number)\ncost(a, c) :- alpha__size(a, c).\ncost(a, c) :- alpha__fee(a, c).\n",
        "rules: column c of cost holds EUR and USD: two currencies in one column"),
    "through-a-derived-relation": (
        ".decl fees(a: symbol, f: number)\nfees(a, f) :- alpha__fee(a, f).\n"
        ".decl both(a: symbol)\nboth(a) :- fees(a, x), alpha__size(a, x).\n",
        r"rules/core\.dl:4: x in both joins EUR and USD"),
    "a-fold-against-another-currency": (
        ".decl paid(a: symbol)\npaid(a) :- alpha__fee(a, t), t = sum s : { alpha__size(a, s) }.\n",
        "bad_aggregate|joins EUR and USD"),
}


@pytest.mark.parametrize("case", sorted(TWO_CURRENCIES))
def test_two_currencies_in_one_variable_or_column_is_an_error(fixture, case):
    text, message = TWO_CURRENCIES[case]
    (fixture / "rules").mkdir()
    (fixture / "rules" / "core.dl").write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(pack.CompileError, match=message):
        pack.read(fixture)
