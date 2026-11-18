"""A board uses the enum's declared order (contracts/view.yaml, Sheet.columns)."""

import json
import shutil

import pytest
from rezono_compiler import emit, pack
from rezono_publication import l0, publication
from support import FIXTURE


def published_orders(folder):
    files = emit.compile_pack(pack.read(folder))
    bundle = json.loads(files["bundle/schema-bundle.json"])
    schema, _ = publication.schema_document(bundle)
    l0.check_schema(schema)
    [enum] = bundle["enums"]
    return enum["values"], schema["enums"]["state"]


def test_pack_enum_reordering_changes_the_published_order(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    schema = folder / "schema" / "minimal.yaml"
    original = schema.read_text(encoding="utf-8")
    declared = "      low: {}\n      high: {}"
    assert original.count(declared) == 1
    schema.write_text(original.replace(declared, "      high: {}\n      low: {}"), encoding="utf-8")
    before = published_orders(folder)

    schema.write_text(original, encoding="utf-8")
    after = published_orders(folder)
    assert before == (["state.high", "state.low"], ["high", "low"])
    assert after == (["state.low", "state.high"], ["low", "high"])
