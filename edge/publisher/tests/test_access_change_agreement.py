"""Publisher and checker must independently agree on whether an assumption may change read access
(decisions/central-read-access.md, section 3). A planted disagreement must block."""

from __future__ import annotations

import hashlib
import json

import pytest

from rezono_checker import access as checker_access
from rezono_publisher import difference, store, views

BUNDLE = {
    "pack": {"id": "sample"},
    "kinds": [
        {"id": "role"},
        {"id": "permit"},
        {"id": "item"},
    ],
    "arrows": [],
    "attributes": [
        {"id": "item.note", "kind": "item", "name": "note", "table": "item__note"},
    ],
    "enums": [],
}

RULES = {
    "format": "rezono.rules/1",
    "relations": [
        {"name": "role", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "permit", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "item", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "item__note", "role": "base", "key": [{"name": "id", "type": "string"}, {"name": "v", "type": "string"}]},
        {"name": "may_read", "role": "derived", "key": [
            {"name": "r", "type": "string"}, {"name": "k", "type": "string"}, {"name": "x", "type": "string"}]},
        {"name": "may_read_full", "role": "derived", "key": [
            {"name": "r", "type": "string"}, {"name": "k", "type": "string"}]},
    ],
    "rules": [
        {
            "id": "r_item",
            "module": "access",
            "head": {"relation": "may_read", "terms": ["?r", "item", "?x"]},
            "body": [
                {"relation": "role", "terms": ["?r"], "polarity": "positive"},
                {"relation": "item", "terms": ["?x"], "polarity": "positive"},
            ],
        },
        {
            "id": "r_full",
            "module": "access",
            "head": {"relation": "may_read_full", "terms": ["?r", "item"]},
            "body": [
                {"relation": "role", "terms": ["?r"], "polarity": "positive"},
                {"relation": "permit", "terms": ["scope"], "polarity": "positive"},
            ],
        },
    ],
}

ACCESS_DELTA = {"format": "rezono.delta/1", "pack": "sample", "changes": [
    {"op": "insert", "file": "facts/all.yaml", "kind": "permit", "key": "scope", "values": {}},
]}
BENIGN_DELTA = {"format": "rezono.delta/1", "pack": "sample", "changes": [
    {"op": "set", "kind": "item", "key": "i1", "slot": "note", "value": "updated"},
]}


class MissingAccessChangeCheck(AssertionError):
    """The checker does not yet independently check access-changing deltas or block on disagreement."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _setup_store(tmp_path) -> store.FileStore:
    st = store.FileStore(tmp_path / "store")
    bundle_bytes = json.dumps(BUNDLE).encode("utf-8")
    rules_bytes = json.dumps(RULES).encode("utf-8")
    bundle_key = "sample/bundles/bundle.json"
    rules_key = "sample/bundles/rules.json"
    st.put_new(bundle_key, bundle_bytes)
    st.put_new(rules_key, rules_bytes)
    snap_before = json.dumps([{"key": ["i1", "before"]}]).encode("utf-8")
    snap_after = json.dumps([{"key": ["i1", "after"]}]).encode("utf-8")
    obj_before = f"sample/objects/{_sha256(snap_before)}.json"
    obj_after = f"sample/objects/{_sha256(snap_after)}.json"
    st.put_new(obj_before, snap_before)
    st.put_new(obj_after, snap_after)
    compiled = [
        {"file": "bundle/schema-bundle.json", "uri": st.uri(bundle_key), "sha256": _sha256(bundle_bytes)},
        {"file": "ir/rules.json", "uri": st.uri(rules_key), "sha256": _sha256(rules_bytes)},
    ]
    base = {
        "id": "m-1",
        "epoch": 1,
        "compiled": compiled,
        "snapshots": [
            {"role": "reader", "relation": "item__note", "complete": False, "full": True, "format": "json",
             "uri": st.uri(obj_before), "sha256": _sha256(snap_before)},
        ],
    }
    proposal = {
        "id": "p-local-1-2",
        "epoch": 2,
        "proposal": "local-1",
        "base_manifest": "m-1",
        "compiled": compiled,
        "snapshots": [
            {"role": "reader", "relation": "item__note", "complete": False, "full": True, "format": "json",
             "uri": st.uri(obj_after), "sha256": _sha256(snap_after)},
        ],
    }
    st.put_new("sample/manifests/m-1.json", json.dumps(base).encode("utf-8"))
    st.put_new("sample/manifests/p-local-1-2.json", json.dumps(proposal).encode("utf-8"))
    return st


def test_publisher_and_checker_disagreement_on_access_change_blocks(tmp_path, monkeypatch):
    checker_fn = getattr(checker_access, "may_change_access", None)
    if checker_fn is None:
        raise MissingAccessChangeCheck("rezono_checker.access.may_change_access is missing")

    # Both sides must independently agree on may_read_full changes, benign edits and missing inputs.
    assert checker_fn(RULES, BUNDLE, ACCESS_DELTA) is True
    assert difference.withheld(RULES, BUNDLE, ACCESS_DELTA) is True
    assert checker_fn(RULES, BUNDLE, BENIGN_DELTA) is False
    assert difference.withheld(RULES, BUNDLE, BENIGN_DELTA) is False
    assert checker_fn(RULES, BUNDLE, None) is True
    assert checker_fn(RULES, None, BENIGN_DELTA) is True

    st = _setup_store(tmp_path)
    # Normal agreement: access-changing delta produces no difference files.
    assert difference.plan(st, "sample", "p-local-1-2", ACCESS_DELTA) == []

    # Planted disagreement 1: publisher wrongly allows an access-changing delta while checker withholds it.
    monkeypatch.setattr(difference, "withheld", lambda *args, **kwargs: False)
    with pytest.raises(views.Blocked):
        difference.plan(st, "sample", "p-local-1-2", ACCESS_DELTA)

    # Planted disagreement 2: publisher wrongly withholds a benign delta while checker allows it.
    monkeypatch.setattr(difference, "withheld", lambda *args, **kwargs: True)
    with pytest.raises(views.Blocked):
        difference.plan(st, "sample", "p-local-1-2", BENIGN_DELTA)
