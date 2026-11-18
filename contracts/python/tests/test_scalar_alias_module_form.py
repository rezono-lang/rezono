"""Scalar aliases are typed declarations of version two of the module form."""

from pathlib import Path

import pytest
from linkml.validator import validate


SCHEMA = str(Path(__file__).resolve().parents[2] / "rezono-module.yaml")
ALIAS = {"type": "Cents", "base": "Int"}


def findings(version: int, declaration: dict[str, object]):
    form = {
        "format": f"rezono.module/{version}",
        "module": {"rezono": "0", "pack": "sample", "use": [], "decls": [declaration]},
        "spans": [{"at": "/decls/0", "line": "3", "start": "26", "end": "31"}],
    }
    return validate(form, SCHEMA, "ModuleForm").results


def test_version_two_accepts_a_typed_scalar_alias():
    assert findings(2, ALIAS) == []


@pytest.mark.parametrize(
    ("version", "declaration"),
    [
        (1, ALIAS),
        (2, {"type": "Cents"}),
        (2, {"base": "Int"}),
        (2, {"type": "cents", "base": "Int"}),
        (2, {"type": "Cents", "base": "int"}),
        (2, {"type": "Cents", "base": ["Int"]}),
        (2, {"type": "Cents", "base": "Int", "extra": "unused"}),
    ],
)
def test_module_form_refuses_an_alias_outside_its_contract(version, declaration):
    assert findings(version, declaration)
