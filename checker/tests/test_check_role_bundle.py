"""check_role derives kinds, parents and columns from the compiled schema bundle itself
(decisions/central-read-access.md, section 4)."""

from __future__ import annotations

import inspect
import json

import pytest

from rezono_checker import access

BUNDLE = {
    "pack": {"id": "sample"},
    "kinds": [
        {"id": "item"},
        {"id": "special", "parent": "item"},
        {"id": "target"},
    ],
    "arrows": [
        {"id": "item.target", "kind": "item", "name": "target", "table": "item__target", "target": "target"},
    ],
    "attributes": [
        {"id": "item.label", "kind": "item", "name": "label", "table": "item__label"},
    ],
    "enums": [
        {"id": "grade", "values": ["high", "low"]},
    ],
}

DOC = {
    "format": "rezono.rules/1",
    "relations": [
        {"name": "item", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "special", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "target", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "item__target", "role": "base", "key": [{"name": "id", "type": "string"}, {"name": "v", "type": "string"}]},
        {"name": "item__label", "role": "base", "key": [{"name": "id", "type": "string"}, {"name": "v", "type": "string"}]},
        {"name": "may_read", "role": "derived", "key": [
            {"name": "r", "type": "string"}, {"name": "k", "type": "string"}, {"name": "x", "type": "string"}]},
    ],
    "rules": [],
}


def _snap(rows: list[list[str]]) -> bytes:
    return json.dumps([{"key": r} for r in rows]).encode("utf-8")


class LegacyCheckRoleSignature(AssertionError):
    """check_role still takes publisher-supplied columns, kinds or parents instead of the schema bundle."""


def test_check_role_derives_schema_from_bundle():
    params = list(inspect.signature(access.check_role).parameters)
    if any(legacy in params for legacy in ("columns", "kinds", "parents")) or "bundle" not in params:
        raise LegacyCheckRoleSignature(f"check_role parameters are still {params}")

    complete = {
        "item": _snap([["i1"], ["s1"]]),
        "special": _snap([["s1"]]),
        "target": _snap([["t_ok"], ["t_secret"]]),
        "item__target": _snap([["i1", "t_ok"], ["i1", "t_secret"]]),
        "item__label": _snap([["i1", "visible"]]),
        "may_read": _snap([
            ["reader", "item", "i1"],
            ["reader", "item", "s1"],
            ["reader", "target", "t_ok"],
        ]),
    }
    good = {
        "item": _snap([["i1"], ["s1"]]),
        # s1 is readable as a special because parent(special) == item comes from bundle.
        "special": _snap([["s1"]]),
        "target": _snap([["t_ok"]]),
        "item__target": _snap([["i1", "t_ok"]]),
        "item__label": _snap([["i1", "visible"]]),
    }
    _, findings = access.check_role("reader", complete, good, None, BUNDLE, DOC)
    assert findings == [], findings

    # Counter-case 1: an arrow row pointing to an unreadable target must be refused via bundle-derived columns.
    leaked_arrow = dict(good, item__target=_snap([["i1", "t_ok"], ["i1", "t_secret"]]))
    _, leaked_findings = access.check_role("reader", complete, leaked_arrow, None, BUNDLE, DOC)
    assert any(f.get("reason") == "not_readable" and f.get("relation") == "item__target" for f in leaked_findings), leaked_findings

    # Counter-case 2: a malformed/empty bundle must fail closed with an error finding.
    _, bad_bundle_findings = access.check_role("reader", complete, good, None, {}, DOC)
    assert bad_bundle_findings and all(f.get("severity") == "error" for f in bad_bundle_findings)
