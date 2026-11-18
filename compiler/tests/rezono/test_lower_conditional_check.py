"""A conditional requirement must retain the legacy schema rule and its violations."""

import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import emit, facts, modules, pack
from support import FIXTURE, violations
from test_rezono_module import module


ROOT = Path(__file__).resolve().parents[3]
ORACLE = ROOT / "examples/library/schema/library.yaml"
READER_CASE = ROOT / "rezono/test/reader_cases/conditional_check.json"


class MissingConditionalLowering(AssertionError):
    """The compiler does not yet lower a module kind's checks member."""


def test_lower_conditional_check(tmp_path):
    legacy = Path(shutil.copytree(FIXTURE, tmp_path / "legacy/minimal"))
    authored = Path(shutil.copytree(FIXTURE, tmp_path / "authored/minimal"))
    library = yaml.safe_load(ORACLE.read_bytes())
    original = library["classes"]["Member"]["rules"]

    branch = {"attributes": {"id": {"identifier": True}}}
    member = {"attributes": {
        "id": {"identifier": True},
        **library["classes"]["Member"]["attributes"],
    }, "rules": original}
    definition = {
        "id": "https://rezono.example/conditional",
        "name": "conditional",
        "in_language": "nl",
        "imports": ["linkml:types"],
        "default_range": "string",
        "annotations": {"layer": "facts"},
        "enums": library["enums"],
        "classes": {"Branch": branch, "Member": member},
    }
    (legacy / "schema/conditional.yaml").write_bytes(yaml.safe_dump(definition, sort_keys=False).encode())

    fixture = json.loads(READER_CASE.read_bytes())
    [member_declaration] = fixture["module"]["decls"]
    module(authored, [
        {"enum": "MembershipType", "world": "closed", "values": ["youth", "adult"]},
        {"kind": "Branch", "world": "closed", "slots": [], "derived": []},
        member_declaration,
    ], name="conditional")
    form = authored / "rezono/conditional.json"
    doc = json.loads(form.read_bytes())
    doc["format"] = "rezono.module/2"
    form.write_bytes(json.dumps(doc, sort_keys=True).encode())

    records = {
        "branch": [{"id": "north"}],
        "member": [
            {"id": "adult-ok", "membership": "adult", "home_branch": "north"},
            {"id": "adult-missing", "membership": "adult"},
            {"id": "youth-missing", "membership": "youth"},
        ],
    }
    oracle = pack.read(legacy)
    expected = violations(emit.compile_pack(oracle), facts.rows_of(oracle, records))
    assert len(expected) == 1
    assert {subject for rows in expected.values() for subject, _ in rows} == {"adult-missing"}

    try:
        model = pack.read(authored)
    except pack.CompileError as error:
        if str(error).strip() == (
            "minimal/rezono/conditional.rezono:30: a kind with checks is not lowered (docs/rezono/publication.md §5.1)"
        ):
            raise MissingConditionalLowering("kind conditional check") from error
        raise
    assert violations(emit.compile_pack(model), facts.rows_of(model, records)) == expected
    errors = []
    loaded, _ = modules.load(authored, pack.read_meta(authored), errors)
    assert not errors
    [schema] = [entry.sv.schema for entry in loaded if "Member" in entry.sv.schema.classes]
    [rule] = schema.classes["Member"].rules
    assert rule.description == original[0]["description"]
    assert rule.preconditions.slot_conditions["membership"].equals_string == "adult"
    assert rule.postconditions.slot_conditions["home_branch"].required is True
