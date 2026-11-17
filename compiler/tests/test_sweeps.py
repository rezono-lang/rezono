"""Sweeps (docs/interaction.md, 1): `explore: {step}` on a slot of whole numbers, and `sweeps.yaml` naming one
fact cell. The minimal fixture, so no domain."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, compile_dir
from rezono_compiler import modules, pack

SWEEP = {"name": "size_scale", "kind": "alpha", "key": "a1", "slot": "size"}


@pytest.fixture
def fixture(tmp_path) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "facts").mkdir()
    write(d / "facts" / "one.yaml", {"alpha": [{"id": "a1", "title": "t", "size": 3}, {"id": "a2", "title": "u"}]})
    explore(d, {"step": 1})
    write(d / "sweeps.yaml", {"sweeps": [SWEEP]})
    return d


def write(path: Path, data) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def edit_schema(d: Path, change) -> None:
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False))


def attribute(d: Path, name: str, **facets) -> None:
    edit_schema(d, lambda s: s["classes"]["Alpha"]["attributes"].setdefault(name, {}).update(facets))


def explore(d: Path, value, slot: str = "size") -> None:
    attribute(d, slot, annotations={"explore": {"value": value}})


def sweeps(d: Path, *entries) -> None:
    write(d / "sweeps.yaml", {"sweeps": list(entries)})


def refused(d: Path, message: str) -> None:
    with pytest.raises(pack.CompileError, match=message):
        pack.read(d)


def test_a_sweep_gets_its_grid_from_the_slot(fixture, tmp_path):
    assert pack.read(fixture).sweeps == [{**SWEEP, "min": 0, "max": 9, "step": 1, "count": 10}]
    files = compile_dir(fixture, tmp_path / "out")
    assert json.loads(files["ir/sweeps.json"]) == {
        "format": "rezono.sweeps/1", "sweeps": [{**SWEEP, "min": 0, "max": 9, "step": 1, "count": 10}]}


def test_explore_may_narrow_the_range_and_the_grid_stops_at_max(fixture):
    explore(fixture, {"min": 2, "max": 9, "step": 3})
    assert pack.read(fixture).sweeps[0] == {**SWEEP, "min": 2, "max": 9, "step": 3, "count": 3}


def test_a_pack_without_sweeps_has_no_sweep_output(tmp_path):
    files = compile_dir(FIXTURE, tmp_path / "out")
    assert "ir/sweeps.json" not in files


def test_sweeps_yaml_is_part_of_the_pack_hash(fixture):
    before = modules.pack_hash(fixture)
    sweeps(fixture, {**SWEEP, "name": "other"})
    assert modules.pack_hash(fixture) != before


def test_a_whole_number_key_is_text(fixture):
    sweeps(fixture, {**SWEEP, "key": 7})
    write(fixture / "facts" / "one.yaml", {"alpha": [{"id": "7", "title": "t"}]})
    assert pack.read(fixture).sweeps[0]["key"] == "7"


@pytest.mark.parametrize("slot, message", [
    ("title", "explore goes on a single slot of whole numbers"),
    ("id", "explore goes on a slot of whole numbers, not on an identifier"),
])
def test_explore_only_on_whole_numbers(fixture, slot, message):
    explore(fixture, {"step": 1}, slot)
    refused(fixture, message)


def test_explore_not_on_an_arrow_or_an_enum(fixture):
    edit_schema(fixture, lambda s: s["classes"]["Beta"]["attributes"]["alpha"].update(annotations={"explore": {"value": {"step": 1}}}))
    refused(fixture, "not on an arrow")
    shutil.rmtree(fixture)
    shutil.copytree(FIXTURE, fixture)
    edit_schema(fixture, lambda s: s["classes"]["Beta"]["attributes"]["state"].update(annotations={"explore": {"value": {"step": 1}}}))
    refused(fixture, "not on an enum")


@pytest.mark.parametrize("value, message", [
    ({"step": 0}, "step must be a whole number above 0"),
    ({"step": -2}, "step must be a whole number above 0"),
    ({"step": True}, "step must be a whole number above 0"),
    ({"min": 0}, "must be a mapping with step"),
    ({"step": 1, "by": 2}, "must be a mapping with step"),
    ({"step": 1, "min": -1}, r"range -1\.\.9 is wider than the slot's 0\.\.9"),
    ({"step": 1, "max": 10}, r"range 0\.\.10 is wider"),
    ({"step": 1, "min": 5, "max": 4}, "min 5 is above max 4"),
    ({"step": 1, "min": 0.5}, "min and max must be whole numbers"),
])
def test_explore_is_checked(fixture, value, message):
    explore(fixture, value)
    refused(fixture, message)


def test_explore_needs_a_range(fixture):
    attribute(fixture, "weight", range="integer", annotations={"explore": {"value": {"step": 1}}})
    refused(fixture, "explore needs a range")


def test_a_grid_above_64_values_names_the_smallest_step_that_fits(fixture):
    attribute(fixture, "size", maximum_value=1000)
    explore(fixture, {"step": 15})
    refused(fixture, "gives 67 values, more than 64; the smallest step that fits is 16")
    explore(fixture, {"step": 16})
    assert pack.read(fixture).sweeps[0]["count"] == 63


@pytest.mark.parametrize("entry, message", [
    ({**SWEEP, "kind": "gamma"}, "'gamma' is not a kind of this pack"),
    ({**SWEEP, "slot": "nope"}, "kind alpha has no slot 'nope'"),
    ({**SWEEP, "slot": "id"}, "kind alpha has no slot 'id'"),
    ({**SWEEP, "slot": "title"}, "slot alpha.title has no `explore"),
    ({**SWEEP, "key": "a9"}, "alpha 'a9' is in no fact file"),
    ({**SWEEP, "key": True}, "key must be text or a whole number"),
    ({**SWEEP, "name": "Size"}, "must be lower snake case"),
    ({**SWEEP, "name": "size-scale"}, "must be lower snake case"),
    ({k: v for k, v in SWEEP.items() if k != "slot"}, "needs exactly name, kind, key and slot"),
    ({**SWEEP, "value": 3}, "needs exactly name, kind, key and slot"),
])
def test_a_sweep_names_one_fact_cell(fixture, entry, message):
    sweeps(fixture, entry)
    refused(fixture, message)


def test_a_record_in_two_fact_files_is_refused(fixture):
    write(fixture / "facts" / "two.yaml", {"alpha": [{"id": "a1", "title": "again"}]})
    refused(fixture, "is in facts/one.yaml, facts/two.yaml")


def test_one_sweep_per_pack_in_v1(fixture):
    sweeps(fixture, SWEEP, {**SWEEP, "name": "second"})
    refused(fixture, "2 sweeps; a pack has at most 1")


@pytest.mark.parametrize("doc", [[SWEEP], {"sweeps": SWEEP}, {"sweeps": [SWEEP], "more": 1}, None])
def test_sweeps_yaml_has_one_list(fixture, doc):
    write(fixture / "sweeps.yaml", doc)
    refused(fixture, "must be a mapping with one key, sweeps, a list")


def test_a_mapping_annotation_without_value_is_a_compile_error(fixture):
    attribute(fixture, "size", annotations={"explore": {"step": 1}})
    refused(fixture, r"schema/minimal.yaml: LinkML cannot read it .*`tag: \{value: \{...\}\}`")
