"""SO-5: pack.yaml may say what the pack's data is (`class`); the compiler reads it as a name and nothing more.
Which profile carries which class is rede_publisher.classes; the compiler knows no class by name."""

import shutil
from pathlib import Path

import pytest
import yaml

from rede_compiler import pack

FIXTURE = Path(__file__).parent / "fixtures" / "minimal"


def with_class(tmp_path, value):
    target = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    meta = yaml.safe_load((target / "pack.yaml").read_text(encoding="utf-8"))
    (target / "pack.yaml").write_text(yaml.safe_dump(meta | {"class": value}, sort_keys=False), encoding="utf-8")
    return target


@pytest.mark.parametrize("value", ["quokka-grade", "unclassified", "a1"])
def test_a_class_is_a_lower_case_name(tmp_path, value):
    assert pack.read_meta(with_class(tmp_path, value))["class"] == value


@pytest.mark.parametrize("value", ["Security", "with space", "-lead", 3, True, ""])
def test_anything_else_is_refused(tmp_path, value):
    with pytest.raises(pack.CompileError, match="class is a lower-case name"):
        pack.read_meta(with_class(tmp_path, value))


def test_no_class_is_no_key():
    assert "class" not in pack.read_meta(FIXTURE)
