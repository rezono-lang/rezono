"""Per-key totality check downgrading in `rezono_publisher.suppose`.

Unsetting a required slot on an existing record may downgrade that check to a warning so the
assumption can answer unknown values, but only when every violating key in that check was
explicitly unset by the delta. Any un-unset violating key (such as an `insert` missing the
required slot, or a pre-existing violation) must still block publication.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, publish, store, suppose as suppose_mod  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[3] / "compiler" / "tests" / "fixtures"
ROLES = {"checker": "complete", "viewer": "may_read"}
KNOWLEDGE_TIME = "2026-01-01T00:00:00Z"
READ_RULES = (
    ".decl may_read(role: symbol, kind: symbol, element: symbol)\n"
    'may_read("viewer", "alpha", a) :- alpha(a).\n'
    'may_read("viewer", "beta", b) :- beta(b).\n'
)


def _pack(tmp_path: Path, *, with_subkind: bool = False) -> tuple[Path, store.FileStore]:
    """Build a minimal neutral pack with a `may_read` role and publish main manifest `m-1`."""
    pack_dir = tmp_path / "minimal"
    shutil.copytree(FIXTURES / "minimal", pack_dir)
    schema_path = pack_dir / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    rules = READ_RULES
    records: dict = {
        "alpha": [{"id": "a1", "title": "one", "size": 1}],
        "beta": [{"id": "b1", "alpha": "a1", "state": "low"}],
    }
    if with_subkind:
        schema["classes"]["SubBeta"] = {"is_a": "Beta"}
        schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
        rules += 'may_read("viewer", "sub_beta", s) :- sub_beta(s).\n'
        records["sub_beta"] = [{"id": "s1", "alpha": "a1", "state": "low"}]
    (pack_dir / "rules").mkdir()
    (pack_dir / "rules" / "access.dl").write_text(rules, encoding="utf-8")
    (pack_dir / "facts").mkdir()
    (pack_dir / "facts" / "a.yaml").write_text(yaml.safe_dump(records, sort_keys=False), encoding="utf-8")

    st = store.FileStore(tmp_path / "store")
    epoch = batch.epoch(pack_dir, epoch=1, knowledge_time=KNOWLEDGE_TIME, sources=[("facts", "1")])
    manifest = publish.publish(epoch, st, ROLES)
    assert manifest["id"] == "m-1"
    return pack_dir, st


def _delta(changes: list[dict]) -> dict:
    return {"format": "rezono.delta/1", "pack": "minimal", "changes": changes}


def test_unset_on_existing_required_slot_is_allowed_and_downgraded_to_warning(tmp_path):
    pack_dir, st = _pack(tmp_path)
    delta = _delta([{"op": "unset", "kind": "beta", "key": "b1", "slot": "alpha"}])

    answer = suppose_mod.suppose(pack_dir, st, "m-1", "viewer", delta)
    assert answer["format"] == suppose_mod.FORMAT
    assert answer["manifest"].startswith("p-local-")
    assert answer["withheld"] is None
    removed = [r for r in answer["rows"] if r["relation"] == "beta__alpha" and r["weight"] == -1]
    assert [r["key"] for r in removed] == [["b1", "a1"]]

    manifest = json.loads(st.get(f"minimal/manifests/{answer['manifest']}.json"))
    totality = next(c for c in manifest["checks"] if c["name"] == "beta__alpha__totality")
    assert totality["status"] == "warning"
    assert totality["violations"] == 1


def test_unset_combined_with_insert_missing_required_slot_is_blocked(tmp_path):
    pack_dir, st = _pack(tmp_path)
    delta = _delta([
        {"op": "unset", "kind": "beta", "key": "b1", "slot": "alpha"},
        {"op": "insert", "file": "facts/a.yaml", "kind": "beta", "key": "b2", "values": {"state": "low"}},
    ])
    mid = f"p-{suppose_mod.proposal_name(delta)}-2"

    with pytest.raises(publish.Blocked, match="beta__alpha__totality"):
        suppose_mod.suppose(pack_dir, st, "m-1", "viewer", delta)
    assert st.get(f"minimal/manifests/{mid}.json") is None


def test_unset_then_set_combined_with_insert_missing_required_slot_is_blocked(tmp_path):
    pack_dir, st = _pack(tmp_path)
    delta = _delta([
        {"op": "unset", "kind": "beta", "key": "b1", "slot": "alpha"},
        {"op": "set", "kind": "beta", "key": "b1", "slot": "alpha", "value": "a1"},
        {"op": "insert", "file": "facts/a.yaml", "kind": "beta", "key": "b2", "values": {"state": "low"}},
    ])
    mid = f"p-{suppose_mod.proposal_name(delta)}-2"

    with pytest.raises(publish.Blocked, match="beta__alpha__totality"):
        suppose_mod.suppose(pack_dir, st, "m-1", "viewer", delta)
    assert st.get(f"minimal/manifests/{mid}.json") is None


def test_unset_delete_insert_same_key_missing_required_slot_is_blocked(tmp_path):
    pack_dir, st = _pack(tmp_path)
    delta = _delta([
        {"op": "unset", "kind": "beta", "key": "b1", "slot": "alpha"},
        {"op": "delete", "kind": "beta", "key": "b1"},
        {"op": "insert", "file": "facts/a.yaml", "kind": "beta", "key": "b1", "values": {"state": "low"}},
    ])
    mid = f"p-{suppose_mod.proposal_name(delta)}-2"

    with pytest.raises(publish.Blocked, match="beta__alpha__totality"):
        suppose_mod.suppose(pack_dir, st, "m-1", "viewer", delta)
    assert st.get(f"minimal/manifests/{mid}.json") is None


def test_subkind_unset_allowed_but_subkind_insert_missing_inherited_required_slot_is_blocked(tmp_path):
    pack_dir, st = _pack(tmp_path, with_subkind=True)

    allowed_delta = _delta([{"op": "unset", "kind": "sub_beta", "key": "s1", "slot": "alpha"}])
    answer = suppose_mod.suppose(pack_dir, st, "m-1", "viewer", allowed_delta)
    manifest = json.loads(st.get(f"minimal/manifests/{answer['manifest']}.json"))
    totality = next(c for c in manifest["checks"] if c["name"] == "beta__alpha__totality")
    assert totality["status"] == "warning"
    assert totality["violations"] == 1

    bypass_delta = _delta([
        {"op": "unset", "kind": "sub_beta", "key": "s1", "slot": "alpha"},
        {"op": "insert", "file": "facts/a.yaml", "kind": "sub_beta", "key": "s2", "values": {"state": "low"}},
    ])
    mid = f"p-{suppose_mod.proposal_name(bypass_delta)}-2"
    with pytest.raises(publish.Blocked, match="beta__alpha__totality"):
        suppose_mod.suppose(pack_dir, st, "m-1", "viewer", bypass_delta)
    assert st.get(f"minimal/manifests/{mid}.json") is None


def test_may_downgrade_totality_fails_closed_on_preexisting_violation_or_mismatch():
    tables = {"beta__alpha__totality": ("beta", "beta__alpha")}
    unset = {"beta__alpha__totality": {"b1"}}
    check_one = {"name": "beta__alpha__totality", "status": "red", "violations": 1}
    check_two = {"name": "beta__alpha__totality", "status": "red", "violations": 2}

    # Exact single unset key matches: allowed.
    rows_exact = {"beta": [("b1",), ("b2",)], "beta__alpha": [("b2", "a1")]}
    assert suppose_mod._may_downgrade_totality(check_one, rows_exact, tables, unset)

    # Pre-existing violation on b2 alongside unset b1: refused.
    rows_extra = {"beta": [("b1",), ("b2",)], "beta__alpha": []}
    assert not suppose_mod._may_downgrade_totality(check_two, rows_extra, tables, unset)
    assert not suppose_mod._may_downgrade_totality(check_one, rows_extra, tables, unset)

    # Unrelated violating key b2 with count 1: refused.
    rows_other = {"beta": [("b1",), ("b2",)], "beta__alpha": [("b1", "a1")]}
    assert not suppose_mod._may_downgrade_totality(check_one, rows_other, tables, unset)

    # Missing table in rows: fail closed.
    assert not suppose_mod._may_downgrade_totality(check_one, {"beta": [("b1",)]}, tables, unset)
