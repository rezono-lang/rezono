"""Checks as data (decision E11): one view per check kind, metadata as rows from the definition only."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import checks, emit, facts, pack, writer
from support import FIXTURE, REPO, compile_dir, text, violations


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def edit_schema(d: Path, change) -> None:
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False))


def made(sql: str) -> list[str]:
    return re.findall(r'^CREATE (?:MATERIALIZED|LOCAL) VIEW "([^"]+)"', sql, re.M)


def test_one_view_per_check_kind(fixture, tmp_path):
    """The views do not follow the slots: the generic check kinds, the local relations and the union."""
    files = compile_dir(fixture, tmp_path / "out")
    views = made(files["engine/integrity.sql"])
    assert views == ["rezono__element", "rezono__value", "rezono__integer", "rezono__enum_value"] + [
        checks.P + c for c in checks.GENERIC] + ["validation_result"]
    logical = emit.integrity(pack.read(fixture))
    assert len(logical) > len(checks.GENERIC) and not set(views) & {c[0] for c in logical}


def test_the_bundle_names_each_logical_check_and_its_view(fixture, tmp_path):
    files = compile_dir(fixture, tmp_path / "out")
    entries = json.loads(files["bundle/schema-bundle.json"])["checks"]
    assert {"view": "beta__alpha__totality", "relation": "rezono__totality", "check": "totality", "kind": "beta",
            "subject": "alpha", "path": "alpha"} in entries
    assert all(e["relation"] == checks.P + e["check"] for e in entries)


def test_metadata_rows_say_which_slot_has_which_check(fixture, tmp_path):
    params = json.loads(compile_dir(fixture, tmp_path / "out")["engine/parameters.json"])
    assert params["rezono__required"] == [{"kind": "alpha", "slot": "title"}, {"kind": "beta", "slot": "alpha"}]
    assert params["rezono__arrow"] == [{"kind": "beta", "slot": "alpha", "target": "alpha"}]
    assert params["rezono__enum"] == [{"kind": "beta", "slot": "state", "enumeration": "state"}]
    assert params["rezono__minimum"] == [{"kind": "alpha", "slot": "size", "v": 0}]
    assert params["rezono__maximum"] == [{"kind": "alpha", "slot": "size", "v": 9}]
    assert params["rezono__is_a"] == [] and params["rezono__constant"] == []


CHANGES = {
    "a required slot made optional": lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(required=False),
    "an optional slot made required": lambda s: s["classes"]["Beta"]["attributes"]["state"].update(required=True),
    "a required arrow made optional": lambda s: s["classes"]["Beta"]["attributes"]["alpha"].update(required=False),
    "an arrow to another kind with the same id type": lambda s: s["classes"]["Beta"]["attributes"]["alpha"].update(
        range="Gamma"),
    "another enum on a text slot": lambda s: s["classes"]["Beta"]["attributes"]["state"].update(range="Level"),
    "a bound changed": lambda s: s["classes"]["Alpha"]["attributes"]["size"].update(maximum_value=7),
    "a bound removed": lambda s: s["classes"]["Alpha"]["attributes"]["size"].pop("minimum_value"),
    "a constant added": lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(equals_string="t"),
    "a cardinality limit added": lambda s: s["classes"]["Beta"]["attributes"]["state"].update(
        multivalued=True, maximum_cardinality=2),
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_a_schema_change_of_a_check_is_a_change_of_rows(fixture, tmp_path, change):
    """Decision E11: the engine program stays the same bytes, so Feldera does not build; the metadata rows
    and the bundle change. A per-slot parameter table exists only when a rule reads it."""
    def base(s):  # both versions have the kinds and enums the change points to
        s["enums"]["Level"] = {"permissible_values": {"one": {}, "two": {}}}
        s["classes"]["Gamma"] = {"attributes": {"id": {"identifier": True}}}
    edit_schema(fixture, base)
    before = compile_dir(fixture, tmp_path / "before")
    edit_schema(fixture, CHANGES[change])
    after = compile_dir(fixture, tmp_path / "after")
    sql = sorted(f for f in before if f.endswith(".sql"))
    assert sql == sorted(f for f in after if f.endswith(".sql"))
    assert all(before[f] == after[f] for f in sql), [f for f in sql if before[f] != after[f]]
    assert before["engine/parameters.json"] != after["engine/parameters.json"]
    assert before["bundle/schema-bundle.json"] != after["bundle/schema-bundle.json"]


def test_the_rows_follow_a_schema_change(fixture, tmp_path):
    """Making a slot required needs no other SQL: the row alone makes the totality check find it."""
    rows = "alpha: [{id: a, title: t}]\nbeta: [{id: b, alpha: a}]\n"
    (tmp_path / "facts.yaml").write_text(rows)
    files = compile_dir(fixture, tmp_path / "before")
    assert violations(files, facts.load(pack.read(fixture), tmp_path / "facts.yaml")) == {}
    edit_schema(fixture, lambda s: s["classes"]["Beta"]["attributes"]["state"].update(required=True))
    files = compile_dir(fixture, tmp_path / "after")
    assert violations(files, facts.load(pack.read(fixture), tmp_path / "facts.yaml")) == text(
        {"beta__state__totality": {("b",)}})


@pytest.mark.parametrize("name", ["Rezono", "RezonoThing"])
def test_rezono_is_reserved_for_the_engine(fixture, name):
    edit_schema(fixture, lambda s: s["classes"].update({name: {"attributes": {"id": {"identifier": True}}}}))
    if name == "Rezono":
        with pytest.raises(pack.CompileError, match="engine name 'rezono' is reserved"):
            emit.compile_pack(pack.read(fixture))
    else:
        emit.compile_pack(pack.read(fixture))  # rezono_thing is a name of the pack's own


def test_check_metadata_never_comes_from_facts_scenarios_or_a_delta(fixture, tmp_path):
    """Decision E11: rezono__* rows come only from the compiled definition. A fact file, a scenario and a
    delta that name them are refused, so a change of data can never switch a check off."""
    from rezono_compiler import scenarios
    model = pack.read(fixture)
    for section in ("rezono__required", "rezono"):
        (tmp_path / "facts.yaml").write_text(f"{section}: [{{kind: beta, slot: alpha}}]\n")
        with pytest.raises(facts.LoadError, match="unknown kind"):
            facts.load(model, tmp_path / "facts.yaml")
        with pytest.raises(facts.LoadError, match="unknown kind"):
            scenarios.records(model, tmp_path / "facts.yaml")
    library = REPO / "examples" / "library"
    for kind in ("rezono__required", "rezono"):
        change = {"op": "set", "file": "facts/valid.yaml", "kind": kind, "key": "beta", "slot": "slot", "value": "x"}
        with pytest.raises(writer.WriteError):
            writer.apply_delta(library, {"format": writer.FORMAT, "changes": [change]})


def test_a_bound_a_rule_reads_keeps_its_table(fixture, tmp_path):
    """A rule may read a bound (R4): then its per-slot table is there, filled from the same value."""
    (fixture / "rules").mkdir()
    (fixture / "rules" / "r.dl").write_text(".decl big(a: symbol)\nbig(a) :- alpha__size(a, s), alpha__size__maximum(m), s >= m.\n")
    files = compile_dir(fixture, tmp_path / "out")
    params = json.loads(files["engine/parameters.json"])
    assert params["alpha__size__maximum"] == [{"v": 9}] and "alpha__size__minimum" not in params
    assert 'CREATE TABLE "alpha__size__maximum"' in files["engine/tables.sql"]
    assert 'CREATE TABLE "alpha__size__minimum"' not in files["engine/tables.sql"]
