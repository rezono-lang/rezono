"""An unbound `Int` slot must compile like a LinkML `range: integer` slot written separately."""

import json
from pathlib import Path
import shutil

import pytest

from rezono_compiler import facts, pack
from support import FIXTURE, compile_dir
from test_rezono_module import module, unplaced


GAUGE_SCHEMA = """id: https://rezono.example/gauges
name: gauges
imports: [linkml:types, minimal]
default_range: string
annotations: {layer: facts}
classes:
  Gauge:
    attributes:
      id: {identifier: true}
      count: {range: integer, required: true}
      quantity: {range: integer}
"""
GAUGE = {"kind": "Gauge", "world": "closed", "derived": [], "slots": [
    {"slot": "count", "type": "Int"},
    {"slot": "quantity", "type": "Int", "card": "?"},
]}
# Exact signed whole numbers beyond the float range, and an absent optional value.
RECORDS = ("gauge:\n  - {id: g1, count: -4, quantity: 9007199254740993}\n"
           "  - {id: g2, count: 9007199254740993}\n")


def written(tmp_path, how):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / how / "minimal"))
    if how == "schema":
        (directory / "schema/gauges.yaml").write_text(GAUGE_SCHEMA, encoding="utf-8")
    else:
        module(directory, [GAUGE], name="gauges")
    return directory


def test_lower_extended_scalar(tmp_path):
    files = {how: compile_dir(written(tmp_path, how), tmp_path / "out" / how) for how in ("schema", "module")}
    assert sorted(files["schema"]) == sorted(files["module"])
    assert files["module"]["engine/tables.sql"] == files["schema"]["engine/tables.sql"]
    bundles = {how: json.loads(files[how]["bundle/schema-bundle.json"]) for how in files}
    expected = unplaced(json.loads(files["schema"]["bundle/schema-bundle.json"]
                                   .replace('"schema/gauges.yaml"', '"rezono/gauges.rezono"')))
    assert unplaced(bundles["module"])["attributes"] == expected["attributes"]

    data = tmp_path / "gauges.yaml"
    data.write_text(RECORDS, encoding="utf-8")
    rows = {how: facts.load(pack.read(tmp_path / how / "minimal"), data) for how in files}
    assert rows["module"] == rows["schema"]
    assert rows["schema"]["gauge__count"] == [("g1", -4), ("g2", 9007199254740993)]
    assert rows["schema"]["gauge__quantity"] == [("g1", 9007199254740993)]


def test_a_declared_int_keeps_its_declaration(tmp_path):
    """Compatibility control: a kind named Int in the same module stays a reference to that kind."""
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    declared = {"kind": "Int", "world": "closed", "slots": [], "derived": []}
    module(directory, [declared, GAUGE], name="gauges")
    model = pack.read(directory)
    assert model.slot("gauge", "count").range == "int"
