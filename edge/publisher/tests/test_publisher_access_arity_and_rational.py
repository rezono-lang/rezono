"""Counterexample tests for row-arity checking and rational calc inputs in publisher access."""

from __future__ import annotations

import pytest

from rezono_canon import canonical_json
from rezono_checker import access as checker_access
from rezono_publisher import access, publish

KINDS = frozenset({"doc", "person"})
COLUMNS = {
    "doc": ("doc",),
    "person": ("person",),
    "doc__author": ("doc", "person"),
    "grant": ("doc", None),
    "role": (None,),
}
BUNDLE = {
    "kinds": [{"id": "doc"}, {"id": "person"}],
    "arrows": [{"table": "doc__author", "kind": "doc", "target": "person"}],
    "attributes": [{"table": "grant", "kind": "doc"}],
    "enums": [{"id": "role"}],
}


def _ref(relation: str, *parts: str) -> dict:
    return {"relation": relation, "key": canonical_json(list(parts))}


def _lit(relation: str, *terms: str) -> dict:
    return {"relation": relation, "terms": list(terms), "polarity": "positive", "stratum": 0}


def _rule(rid: str, head: tuple[str, ...], *body: dict) -> dict:
    return {
        "id": rid,
        "stratum": 1,
        "head": {"relation": head[0], "terms": list(head[1:])},
        "body": list(body),
    }


def _witness(rule_id: str, head: tuple[str, ...], bindings: dict[str, str], *premises: tuple[str, ...]) -> dict:
    return {
        "conclusion": _ref(*head),
        "rule_id": rule_id,
        "bindings": [{"variable": v, "value": x} for v, x in bindings.items()],
        "premises": [{"row": _ref(*p), "polarity": "positive", "stratum": 0} for p in premises],
    }


def _base_rules() -> dict:
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
            _rule("everyone", ("may_read", "?r", "person", "?x"), _lit("role", "?r"), _lit("person", "?x")),
            _rule("granted", ("may_read", "?r", "doc", "?x"), _lit("grant", "?x", "?r")),
        ],
    }


def _base_rows() -> dict:
    return {
        "role": [("guest",)],
        "person": [("p1",)],
        "doc": [("d1",)],
        "doc__author": [("d1", "p1")],
        "grant": [("d1", "guest")],
        "may_read": [("guest", "person", "p1"), ("guest", "doc", "d1")],
    }


@pytest.mark.parametrize("bad_row", [("d1",), ("d1", "p1", "secret-extra")])
def test_publisher_access_refuses_mismatched_arity_rows(bad_row: tuple[str, ...]):
    """A row with too few or too many columns must be refused fail-closed by Scope and for_role."""
    rows = _base_rows()
    rows["doc__author"] = [bad_row]
    with pytest.raises(ValueError, match="doc__author"):
        access.for_role(rows, KINDS, {}, COLUMNS, _base_rules(), [], "guest")

    scope = access.Scope(_base_rows(), KINDS, {}, COLUMNS, _base_rules(), "guest")
    with pytest.raises(ValueError, match="doc__author"):
        scope.readable("doc__author", bad_row)


def test_publisher_scope_accepts_list_role_rows():
    """List-typed rows in rows['role'] still match Scope.named while bad-arity list rows fail closed."""
    rows = _base_rows()
    rows["role"] = [["guest"]]
    scope = access.Scope(rows, KINDS, {}, COLUMNS, _base_rules(), "guest")
    assert scope.named is True
    assert "person" in scope.full
    assert scope.full.evidence == ({"kind": "person", "rule": "everyone", "ground": ["role", "guest"]},)

    rows_bad = _base_rows()
    rows_bad["role"] = [["guest", "extra"]]
    with pytest.raises(ValueError, match="role"):
        access.Scope(rows_bad, KINDS, {}, COLUMNS, _base_rules(), "guest")


def _calc_setup(value: str, value_type: str = "rational") -> tuple[dict, dict, dict, list[dict], list[dict]]:
    selection = "calc__share"
    doc = _base_rules()
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
        _rule("received", ("received", "?d", "?v"), _lit(selection, "?d", "?v", "known", ""))
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
    rows = _base_rows() | {
        "doc": [("d1",), ("d2",)],
        "calc__as_of": [],
        selection: [calc_row_d1, calc_row_d2],
        "received": [("d1", value), ("d2", value)],
    }
    everyone = _witness("everyone", ("may_read", "guest", "person", "p1"), {"?r": "guest", "?x": "p1"},
                        ("role", "guest"), ("person", "p1"))
    granted = _witness("granted", ("may_read", "guest", "doc", "d1"), {"?r": "guest", "?x": "d1"},
                       ("grant", "d1", "guest"))
    rec_d1 = _witness("received", ("received", "d1", value), {"?d": "d1", "?v": value}, (selection, *calc_row_d1))
    rec_d2 = _witness("received", ("received", "d2", value), {"?d": "d2", "?v": value}, (selection, *calc_row_d2))
    calc_w_d1 = {"conclusion": _ref(selection, *calc_row_d1), "rule": "share", "version": "v", "premises": []}
    calc_w_d2 = {"conclusion": _ref(selection, *calc_row_d2), "rule": "share", "version": "v", "premises": []}
    return rows, doc, calc_ir, [everyone, granted, rec_d1, rec_d2], [calc_w_d1, calc_w_d2]


@pytest.mark.parametrize("value", ["7/3", "-7/3", "2782/41", "42", "0"])
def test_publisher_and_checker_agree_on_rational_calc_input_for_filtered_role(value: str):
    """A filtered role reading subject d1 receives rational calc inputs, derived rows and witnesses cleanly."""
    rows, doc, calc_ir, witnesses, calc_witnesses = _calc_setup(value, value_type="rational")
    readable, sees, full = access.for_role(rows, KINDS, {}, COLUMNS, doc, witnesses, "guest", calc_ir, calc_witnesses)
    assert readable["calc__share"] == [("d1", value, "known", "")]
    assert readable["received"] == [("d1", value)]
    assert [w["conclusion"] for w in sees["calc_witnesses"]] == [_ref("calc__share", "d1", value, "known", "")]
    assert any(w["conclusion"] == _ref("received", "d1", value) for w in sees["witnesses"])

    complete = {rel: publish.snapshot(rs) for rel, rs in rows.items()}
    mine = {rel: publish.snapshot(rs) for rel, rs in readable.items()}
    verified, findings = checker_access.check_role(
        "guest", complete, mine, full, BUNDLE, doc, calc_ir, witnesses, calc_witnesses,
        sees["calc_witnesses"], sees["witnesses"], claimed_evidence=full.evidence,
    )
    assert findings == [], findings
    assert verified == full


@pytest.mark.parametrize("bad_value", ["7/0", "7/1", "6/4", "-0", "", "7/-3", "01", "abc"])
def test_publisher_rejects_malformed_rational_calc_input_fail_closed(bad_value: str):
    """Malformed rational calc inputs are rejected fail-closed in both publisher and checker."""
    rows, doc, calc_ir, witnesses, calc_witnesses = _calc_setup(bad_value, value_type="rational")
    readable, sees, full = access.for_role(rows, KINDS, {}, COLUMNS, doc, witnesses, "guest", calc_ir, calc_witnesses)
    assert readable["received"] == []
    assert not any(w["conclusion"]["relation"] == "received" for w in sees["witnesses"])

    complete = {rel: publish.snapshot(rs) for rel, rs in rows.items()}
    mine = {rel: publish.snapshot(rs) for rel, rs in readable.items()}
    _, findings = checker_access.check_role(
        "guest", complete, mine, full, BUNDLE, doc, calc_ir, witnesses, calc_witnesses,
        sees["calc_witnesses"], sees["witnesses"], claimed_evidence=full.evidence,
    )
    assert findings == [], findings


def test_publisher_still_rejects_fraction_in_integer_calc_input():
    """An integer-typed calc input still refuses non-integer fractions like 7/3."""
    rows, doc, calc_ir, witnesses, calc_witnesses = _calc_setup("7/3", value_type="integer")
    readable, sees, full = access.for_role(rows, KINDS, {}, COLUMNS, doc, witnesses, "guest", calc_ir, calc_witnesses)
    assert readable["received"] == []
    assert not any(w["conclusion"]["relation"] == "received" for w in sees["witnesses"])

    complete = {rel: publish.snapshot(rs) for rel, rs in rows.items()}
    mine = {rel: publish.snapshot(rs) for rel, rs in readable.items()}
    _, findings = checker_access.check_role(
        "guest", complete, mine, full, BUNDLE, doc, calc_ir, witnesses, calc_witnesses,
        sees["calc_witnesses"], sees["witnesses"], claimed_evidence=full.evidence,
    )
    assert findings == [], findings
