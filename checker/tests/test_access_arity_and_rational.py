"""Counterexample tests for row-arity checking and rational calc inputs in checker access."""

from __future__ import annotations

import json

import pytest

from rezono_checker import access
from rezono_checker.canon import encode_key

BUNDLE = {
    "kinds": [{"id": "doc"}, {"id": "person"}],
    "arrows": [{"table": "doc__author", "kind": "doc", "target": "person"}],
    "attributes": [{"table": "grant", "kind": "doc"}],
    "enums": [{"id": "role"}],
}


def _snap(rows: list[tuple[str, ...]]) -> bytes:
    return json.dumps([{"key": list(r)} for r in sorted(rows)]).encode("utf-8")


def _ref(relation: str, *parts: str) -> dict:
    return {"relation": relation, "key": encode_key(parts)}


def _atom(relation: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": relation, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _rule(rid: str, stratum: str, head: tuple[str, ...], *body: dict) -> dict:
    return {
        "id": rid,
        "stratum": stratum,
        "head": {"relation": head[0], "terms": list(head[1:])},
        "body": list(body),
    }


def _instance(rule_id: str, head: tuple[str, ...], bindings: dict[str, str], *premises: tuple[str, ...]) -> dict:
    return {
        "conclusion": _ref(*head),
        "rule_id": rule_id,
        "bindings": [{"variable": v, "value": x} for v, x in bindings.items()],
        "premises": [{"row": _ref(*p), "polarity": "positive", "stratum": 0} for p in premises],
    }


def _base_doc() -> dict:
    return {
        "format": "rezono.rules/1",
        "pack": "example",
        "relations": [
            {
                "name": "may_read",
                "role": "derived",
                "key": [{"name": c, "type": "string"} for c in ("role", "kind", "id")],
            },
        ],
        "rules": [
            _rule("everyone", "1", ("may_read", "?r", "person", "?x"), _atom("role", "?r"), _atom("person", "?x")),
            _rule("granted", "1", ("may_read", "?r", "doc", "?x"), _atom("grant", "?x", "?r")),
        ],
    }


def _base_world() -> dict:
    everyone = _instance("everyone", ("may_read", "guest", "person", "p1"), {"?r": "guest", "?x": "p1"},
                         ("role", "guest"), ("person", "p1"))
    granted = _instance("granted", ("may_read", "guest", "doc", "d1"), {"?r": "guest", "?x": "d1"},
                        ("grant", "d1", "guest"))
    return {
        "complete": {
            "role": [("guest",)],
            "person": [("p1",)],
            "doc": [("d1",)],
            "doc__author": [("d1", "p1")],
            "grant": [("d1", "guest")],
            "may_read": [("guest", "person", "p1"), ("guest", "doc", "d1")],
        },
        "mine": {
            "role": [("guest",)],
            "person": [("p1",)],
            "doc": [("d1",)],
            "doc__author": [("d1", "p1")],
            "grant": [("d1", "guest")],
            "may_read": [("guest", "person", "p1"), ("guest", "doc", "d1")],
        },
        "full": {"person", "role"},
        "instances": [everyone, granted],
        "witnesses": [everyone, granted],
        "evidence": [{"kind": "person", "rule": "everyone", "ground": ["role", "guest"]}],
        "doc": _base_doc(),
    }


def _run_check(w: dict) -> tuple[frozenset, list[dict]]:
    return access.check_role(
        "guest",
        {rel: _snap(rows) for rel, rows in w["complete"].items()},
        {rel: _snap(rows) for rel, rows in w["mine"].items()},
        w["full"],
        BUNDLE,
        w["doc"],
        w.get("calc_ir"),
        w["instances"],
        w.get("calc_all", ()),
        w.get("calc_mine", ()),
        w["witnesses"],
        claimed_evidence=w.get("evidence"),
    )


def test_check_role_refuses_too_few_columns_in_arrow_row():
    """A 1-column row in a 2-column arrow table must not skip checking the missing target column."""
    w = _base_world()
    w["complete"]["doc__author"] = [("d1",)]
    w["mine"]["doc__author"] = [("d1",)]
    _, findings = _run_check(w)
    assert findings
    assert all(f["severity"] == "error" for f in findings)
    assert any(f["relation"] == "doc__author" for f in findings), findings

    # Even when the role's snapshot omits the truncated row, complete's malformed arity fails closed.
    w["mine"]["doc__author"] = []
    _, omitted_findings = _run_check(w)
    assert any(f["reason"] == "malformed_snapshot" and f["relation"] == "doc__author" for f in omitted_findings), omitted_findings


def test_check_role_refuses_too_many_columns_in_arrow_row():
    """A 3-column row in a 2-column arrow table must be refused fail-closed, not silently truncated."""
    w = _base_world()
    w["complete"]["doc__author"] = [("d1", "p1", "secret-extra")]
    w["mine"]["doc__author"] = [("d1", "p1", "secret-extra")]
    _, findings = _run_check(w)
    assert findings
    assert all(f["severity"] == "error" for f in findings)
    assert any(f["relation"] == "doc__author" for f in findings), findings


def test_check_role_refuses_empty_kind_row_without_crashing():
    """A 0-column row in a kind table fails closed as malformed instead of raising IndexError."""
    w = _base_world()
    w["complete"]["person"] = [("p1",), ()]
    _, findings = _run_check(w)
    assert findings
    assert all(f["severity"] == "error" for f in findings)
    assert any(f["reason"] == "malformed_snapshot" and f["relation"] == "person" for f in findings), findings


def _calc_world(value: str, value_type: str = "rational") -> dict:
    w = _base_world()
    selection = "calc__share"
    doc = _base_doc()
    doc["relations"].extend([
        {
            "name": selection,
            "role": "calc",
            "world": "open",
            "key": [
                {"name": "subject", "type": "string"},
                {"name": "value", "type": value_type},
                {"name": "state", "type": "string"},
                {"name": "reason", "type": "string"},
            ],
        },
        {
            "name": "received",
            "role": "derived",
            "world": "open",
            "key": [
                {"name": "subject", "type": "string"},
                {"name": "value", "type": value_type},
            ],
        },
    ])
    doc["rules"].append(
        _rule(
            "received",
            "1",
            ("received", "?d", "?v"),
            _atom(selection, "?d", "?v", "known", ""),
        )
    )
    calc_ir = {
        "format": "rezono.calc-ir/1",
        "subject": "doc",
        "as_of": "calc__as_of",
        "rules": [{"rule": "share", "view": selection, "type": "number", "versions": ["share@v"]}],
        "facts": [{"id": "people", "reads": "presence", "table": "person"}],
        "versions": [
            {
                "id": "share@v",
                "view": "calc__share__v",
                "definitions": [{"when": {"boolean": True}, "value": {"fact": "people"}}],
            }
        ],
    }
    calc_row_d1 = ("d1", value, "known", "")
    calc_row_d2 = ("d2", value, "known", "")
    calc_w_d1 = {"conclusion": _ref(selection, *calc_row_d1), "rule": "share", "version": "v", "premises": []}
    calc_w_d2 = {"conclusion": _ref(selection, *calc_row_d2), "rule": "share", "version": "v", "premises": []}
    rec_d1 = _instance("received", ("received", "d1", value), {"?d": "d1", "?v": value}, (selection, *calc_row_d1))
    rec_d2 = _instance("received", ("received", "d2", value), {"?d": "d2", "?v": value}, (selection, *calc_row_d2))
    w["doc"] = doc
    w["calc_ir"] = calc_ir
    w["complete"]["doc"] = [("d1",), ("d2",)]
    w["complete"]["calc__as_of"] = []
    w["complete"][selection] = [calc_row_d1, calc_row_d2]
    w["complete"]["received"] = [("d1", value), ("d2", value)]
    w["mine"]["calc__as_of"] = []
    w["mine"][selection] = [calc_row_d1]
    w["mine"]["received"] = [("d1", value)]
    w["full"] = {"person", "role", "calc__as_of"}
    w["instances"] = [*w["instances"], rec_d1, rec_d2]
    w["witnesses"] = [*w["witnesses"], rec_d1]
    w["calc_all"] = [calc_w_d1, calc_w_d2]
    w["calc_mine"] = [calc_w_d1]
    return w


@pytest.mark.parametrize("value", ["7/3", "-7/3", "2782/41", "42", "0"])
def test_check_role_accepts_rational_calc_input_and_witness_for_filtered_role(value: str):
    """A filtered role with read access to a subject sees rational calc inputs and their rule witnesses."""
    w = _calc_world(value, value_type="rational")
    full, findings = _run_check(w)
    assert findings == [], findings
    assert full == frozenset(w["full"])


@pytest.mark.parametrize("bad_value", ["7/0", "7/1", "6/4", "-0", "", "7/-3", "01", "abc"])
def test_check_role_rejects_malformed_rational_calc_input_fail_closed(bad_value: str):
    """Malformed rational calc inputs must never become usable rule premises for a filtered role."""
    w = _calc_world(bad_value, value_type="rational")
    _, findings = _run_check(w)
    reasons = {f["reason"] for f in findings}
    assert "not_derivable" in reasons and "choice_mismatch" in reasons, findings


def test_check_role_still_rejects_fraction_in_integer_calc_input():
    """An integer-typed calc input must still reject non-integer fractions like 7/3."""
    w = _calc_world("7/3", value_type="integer")
    _, findings = _run_check(w)
    reasons = {f["reason"] for f in findings}
    assert "not_derivable" in reasons and "choice_mismatch" in reasons, findings
