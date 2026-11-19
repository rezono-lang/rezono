"""The protected admission inputs are withheld from every filtered role (decisions/admission-transport.md,
section 6), by the checker's own list. Whether the rule IR declares them does not matter: a role handed a row of
one is `not_readable`, and none of them counts as read in full."""

import json

import pytest
from rezono_checker.access import check_role

PROTECTED = {"verified_receipt": ["r1", "example-register", "scope", "cut", "inventory", "content"],
             "verified_member": ["r1", '["partition-a"]', "0", "partition-a"],
             "verified_round": ["round-1", "run-a", "cut-a", "batch-a"],
             "verified_round_member": ["round-1", "step-a"]}
ROWS = {"role": [["guest"]], "may_read": [["guest", "role", "guest"]], **{rel: [row] for rel, row in PROTECTED.items()}}
COLUMNS = {"role": ("role",), "may_read": ("role", None, None),
           **{rel: (None,) * len(row) for rel, row in PROTECTED.items()}}
GRANT = {"id": "r-role", "head": {"relation": "may_read", "terms": ["?r", "role", "?x"]},
         "body": [{"relation": "role", "terms": ["?r"], "polarity": "positive"},
                  {"relation": "role", "terms": ["?x"], "polarity": "positive"}]}


def snaps(rows: dict) -> dict:
    return {rel: json.dumps([{"key": r} for r in rs]).encode() for rel, rs in rows.items()}


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "undeclared"])
def test_every_protected_input_is_withheld_from_a_role(declared):
    relations = [{"name": "may_read", "role": "derived", "key": []}]
    if declared:
        relations += [{"name": rel, "role": "base", "key": []} for rel in PROTECTED]
    doc = {"format": "rezono.rules/1", "pack": "toy", "relations": relations, "rules": [GRANT]}
    mine = {rel: rows for rel, rows in ROWS.items() if rel != "may_read"}
    full, findings = check_role("guest", snaps(ROWS), snaps(mine), None, COLUMNS, ["role"], {}, doc)
    assert full.isdisjoint(PROTECTED)
    assert sorted((f["reason"], f["relation"]) for f in findings if f["relation"] in PROTECTED) == sorted(
        ("not_readable", rel) for rel in PROTECTED)
