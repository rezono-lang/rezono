"""What if, locally on the batch engine (decisions/local-suppose.md), on `subsidy` for the policy adviser.

The base is the pack's facts, the state `0-applications` of reference.py, published as the main manifest
`m-1`. Each test asks one assumption with `rezono_publisher.suppose.suppose` and reads its answer
(`rezono.supposition/1`). The expected award difference comes from examples/subsidy/reference.py, which
shares no code with the engine; it is computed here for the same single delta.
Needs the compiler with DuckDB and the publisher.
"""

import copy
from fractions import Fraction

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from subsidy_test_support import HERE, published, reference  # noqa: E402

ROLE = "policy_adviser"
AWARD = "calc__award"
LEDGER = ("ledger_payment", "period_close", "closed_payment", "calc__payment_difference")  # not read by ROLE
SUPPOSED = {"id": "supposed-allowance", "title": "Supposed: higher advice allowance", "valid_from": "2026-01-01",
            "valid_from_day": 20260101, "state": "proposed"}
# The step of docs/tutorial.md: the advice allowance from 15000 to 25000 cents, on a proposed decision.
ALLOWANCE = {"format": "rezono.delta/1", "pack": "subsidy", "changes": [
    {"op": "insert", "file": "facts/scheme.yaml", "kind": "decision", "key": SUPPOSED["id"],
     "values": {k: v for k, v in SUPPOSED.items() if k != "id"}},
    {"op": "set", "kind": "scheme_parameter", "key": "par-07", "slot": "value", "value": 25000},
    {"op": "set", "kind": "scheme_parameter", "key": "par-07", "slot": "decision", "value": SUPPOSED["id"]}]}
# The same parameter without a value: what rests on it becomes unknown, never zero.
NO_ALLOWANCE = {"format": "rezono.delta/1", "pack": "subsidy", "changes": [
    {"op": "unset", "kind": "scheme_parameter", "key": "par-07", "slot": "value"}]}
# A new role changes the closure of may_read: no difference, with the reason.
NEW_ROLE = {"format": "rezono.delta/1", "pack": "subsidy", "changes": [
    {"op": "insert", "file": "facts/roles.yaml", "kind": "role", "key": "auditor", "values": {"title": "Auditor"}}]}


class MissingLocalSuppose(ImportError):
    pass


def command():
    try:
        from rezono_publisher.suppose import suppose
    except ImportError as error:
        raise MissingLocalSuppose("edge/publisher/rezono_publisher/suppose.py: suppose()") from error
    return suppose


_BASE = []


def published_base(factory):
    """The main manifest m-1, published once per module, after the command was found."""
    if not _BASE:
        store, _ = published(HERE, factory.mktemp("store"))
        _BASE.append(store)
    return _BASE[0]


def facts():
    ref = reference()
    label, state = next(ref.states())
    assert label == "0-applications"
    return ref, copy.deepcopy(state)


def awards(answer):
    return [r for r in answer["rows"] if r["relation"] == AWARD]


def test_a_local_assumption_moves_the_awards_as_the_reference_does(tmp_path_factory):
    suppose = command()
    base = published_base(tmp_path_factory)
    ref, before = facts()
    after = copy.deepcopy(before)
    after["decision"][SUPPOSED["id"]] = dict(SUPPOSED)
    after["scheme_parameter"]["par-07"].update(value=25000, decision=SUPPOSED["id"])
    known = lambda t: {a: int(v) for a, v in ref.calc(t)["award"].items() if v != "unknown"}  # noqa: E731
    was, now = known(before), known(after)
    want = sum(now.values()) - sum(was.values())
    moved = {a for a in set(was) | set(now) if was.get(a) != now.get(a)}
    assert want > 0 and moved

    answer = suppose(HERE, base, "m-1", ROLE, ALLOWANCE)
    assert (answer["format"], answer["base_manifest"], answer["role"]) == ("rezono.supposition/1", "m-1", ROLE)
    assert answer["manifest"].startswith("p-local-") and answer["withheld"] is None
    rows = awards(answer)
    assert {r["row"]["subject"] for r in rows} == moved  # no award that does not move, none left out
    assert sum(r["weight"] * Fraction(r["row"]["value"]) for r in rows if r["row"]["state"] == "known") == want


def test_every_row_of_an_assumption_has_a_weight_and_a_witness(tmp_path_factory):
    suppose = command()
    base = published_base(tmp_path_factory)
    answer = suppose(HERE, base, "m-1", ROLE, ALLOWANCE)
    rows = answer["rows"]
    assert rows
    assert {r["weight"] for r in rows} <= {1, -1}
    sides = {}
    for r in rows:
        sides.setdefault((r["relation"], r["weight"]), []).append(tuple(r["key"]))
    for side in sides.values():
        assert len(side) == len(set(side))  # one row once per side
    for r in rows:
        assert r["witness"] and base.get(r["witness"]) is not None, r
    assert not [r for r in rows if r["relation"].startswith(LEDGER)]
    # A changed award is one row out and one row in: the same application on both sides.
    out = sorted(r["row"]["subject"] for r in awards(answer) if r["weight"] == -1)
    into = sorted(r["row"]["subject"] for r in awards(answer) if r["weight"] == 1)
    assert out == into


def test_an_award_that_becomes_unknown_is_answered_with_its_reason(tmp_path_factory):
    suppose = command()
    base = published_base(tmp_path_factory)
    ref, before = facts()
    steps = {a: ref.award(before, a) for a in sorted(before["application"])}
    resting = {a for a, s in steps.items() if s["award"] != "unknown" and s["advice_allowance"] != "unknown"
               and s["advice_allowance"] > 0}
    apart = {a for a, s in steps.items() if s["award"] != "unknown" and not ref.advised(before, a)}
    assert resting and apart

    answer = suppose(HERE, base, "m-1", ROLE, NO_ALLOWANCE)
    assert answer["withheld"] is None
    into = {r["row"]["subject"]: r["row"] for r in awards(answer) if r["weight"] == 1}
    for a in resting:
        assert into[a]["state"] == "unknown" and into[a]["reason"], into.get(a)
        assert into[a]["value"] == "", into[a]  # empty unless known (calc_sql.value_text): never zero
    assert not apart & {r["row"]["subject"] for r in awards(answer)}


def test_an_assumption_that_may_change_access_gives_no_difference(tmp_path_factory):
    suppose = command()
    base = published_base(tmp_path_factory)
    answer = suppose(HERE, base, "m-1", ROLE, NEW_ROLE)
    assert answer["rows"] == []
    assert isinstance(answer["withheld"], str) and answer["withheld"].strip()
