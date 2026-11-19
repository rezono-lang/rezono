"""A unit written in a module must compile to the unit that the existing LinkML spelling of the same type gives."""

from pathlib import Path
import shutil

import pytest
import yaml

from support import FIXTURE
from test_rezono_module import module
from rezono_compiler import pack


def legacy(tmp_path: Path) -> Path:
    """The fixture pack with the unit as a schema file writes it (P10.3: a whole-number type with `currency`)."""
    d = Path(shutil.copytree(FIXTURE, tmp_path / "legacy" / "minimal"))
    source = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(source.read_bytes())
    schema["types"]["Cents"] = {"typeof": "integer", "annotations": {"currency": "EUR"}}
    source.write_bytes(yaml.safe_dump(schema, sort_keys=False).encode("utf-8"))
    return d


def test_lower_units(tmp_path):
    expected = pack.read(legacy(tmp_path)).units
    assert expected["Cents"].currency == "EUR"

    candidate = Path(shutil.copytree(FIXTURE, tmp_path / "candidate" / "minimal"))
    module(candidate, [{"unit": "Cents", "is": "money minor EUR"}])
    assert pack.read(candidate).units == expected

    # Counter-case: whole euros are not cents. The major unit is refused, never read as its minor unit.
    major = Path(shutil.copytree(FIXTURE, tmp_path / "major" / "minimal"))
    module(major, [{"unit": "Euro", "is": "money EUR"}])
    with pytest.raises(pack.CompileError, match=r"minimal/rezono/m\.rezono:10: .*money minor EUR"):
        pack.read(major)
