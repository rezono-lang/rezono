"""A module may declare the kinds its dataset reads before that dataset, and compiles like the two written apart."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from rezono_compiler import pack, rezono_module, scenarios
from rezono_compiler.__main__ import main
from support import FIXTURE, compile_dir


# The independent form: the kind as a LinkML schema and the rows as a legacy fact file.
GAUGE_SCHEMA = """id: https://rezono.example/gauges
name: gauges
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Gauge:
    attributes:
      id: {identifier: true}
      count: {range: integer, required: true}
      quantity: {range: integer}
"""
RECORDS = "gauge:\n  - {id: g1, count: -4, quantity: 9}\n  - {id: g2, count: 3}\n"
# The same kind and rows in one module: the kind first, then the dataset named after the module.
TOGETHER = """rezono 0
pack minimal
kind Gauge world closed
  count: Int
  quantity: Int?
dataset gauges
  fact Gauge
    | id | count | quantity |
    | g1 | -4    | 9        |
  fact Gauge
    | id | count |
    | g2 | 3     |
"""


class MissingKindsBeforeDataset(AssertionError):
    """A module with kinds before its dataset did not read, compile or load like the kinds and rows written apart."""


def separate(tmp_path):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "separate" / "minimal"))
    (directory / "schema/gauges.yaml").write_text(GAUGE_SCHEMA, encoding="utf-8")
    (directory / "facts").mkdir()
    (directory / "facts/gauges.yaml").write_text(RECORDS, encoding="utf-8")
    return directory


def together(tmp_path, text, name):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    (directory / "rezono").mkdir()
    source = directory / "rezono/gauges.rezono"
    source.write_text(text, encoding="utf-8")
    # The form is what the module reader writes for the source, as `npm run form` does for an author.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("NODE_")}
    written = subprocess.run(["node", str(rezono_module.CHECKOUT_READER), source.name, "gauges.json"],
                             cwd=source.parent, capture_output=True, encoding="utf-8", env=env)
    with (directory / "pack.yaml").open("a", encoding="utf-8") as stream:
        yaml.safe_dump({"rezono": [{"module": "rezono/gauges.rezono", "form": "rezono/gauges.json",
                                    "layer": "facts"}]}, stream)
    return directory, written


def gauges(directory):
    rows = scenarios.states(pack.read(directory), directory)[0][1]
    return {name: sorted(value) for name, value in rows.items() if name.startswith("gauge")}


@pytest.mark.xfail(
    strict=True,
    raises=MissingKindsBeforeDataset,
    reason="M3: decisions/language-library-datasets.md: In compiler/rezono_compiler/rezono_module.py and "
           "compiler/rezono_compiler/facts.py, lower the declarations before the dataset of a module like any "
           "other module at its declared layer, and load the dataset's tables as its facts, instead of expecting "
           "the dataset as the only declaration.",
)
def test_dataset_after_kinds(tmp_path, capsys):
    expected_dir = separate(tmp_path)
    expected_files = compile_dir(expected_dir, tmp_path / "out" / "separate")
    expected = gauges(expected_dir)
    assert expected["gauge__count"] == [("g1", -4), ("g2", 3)]
    # Counter-case of the source: only g1 has a quantity, so an omitted cell must not become a row.
    assert expected["gauge__quantity"] == [("g1", 9)]

    # Counter-case of the module: nothing may follow the dataset, before or after the change.
    after, _ = together(tmp_path, TOGETHER + "kind Extra\n  size: Int\n", "after")
    assert main(["compile", str(after), str(tmp_path / "out" / "after")]) == 1
    capsys.readouterr()

    directory, written = together(tmp_path, TOGETHER, "together")
    if written.returncode != 0:
        raise MissingKindsBeforeDataset(f"the reader refused the module: {written.stderr}")
    status = main(["compile", str(directory), str(tmp_path / "out" / "together")])
    report = capsys.readouterr()
    if status != 0:
        raise MissingKindsBeforeDataset(f"the module did not compile: {report.err}")
    tables = (tmp_path / "out" / "together" / "engine/tables.sql").read_bytes().decode("utf-8")
    if tables != expected_files["engine/tables.sql"]:
        raise MissingKindsBeforeDataset("the kinds of the module lowered to other tables than the LinkML schema")
    actual = gauges(directory)
    if actual != expected:
        raise MissingKindsBeforeDataset(f"the dataset loaded {actual}, not {expected}")
