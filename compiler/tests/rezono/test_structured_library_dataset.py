"""Library fact records retain their shapes before and after typed admission."""

import json
from pathlib import Path

import pytest
import yaml

from rezono_compiler import facts, pack


LIBRARY = Path(__file__).resolve().parents[3] / "examples/library"


def literal(value):
    return {"lit": json.dumps(value)}


def test_structured_library_dataset(tmp_path):
    omitted = {"boundary": "omitted"}
    works = {"fact": "Work", "columns": ["id", "title", "category", "year", "authors"], "rows": [
        [literal("w1"), literal("De avonden"), literal("c1"), literal(1947), {"list": [literal("Gerard Reve")]}],
        [literal("w2"), literal("Moord in de leeszaal"), literal("c2"), omitted,
         {"list": [literal("A. Schrijver"), literal("B. Schrijver")]}],
        [literal("w3"), literal("Empty"), literal("c1"), omitted, {"list": []}],
    ]}
    address = {"record": {"street": literal("Oostweg 5"), "city": literal("Middelburg")}}
    branches = {"fact": "Branch", "columns": ["code", "name", "address"], "rows": [
        [literal("oost"), literal("Vestiging Oost"), address],
    ]}
    form = {"format": "rezono.module/2", "spans": [], "module": {
        "rezono": "0", "pack": "library", "use": [], "decls": [{"dataset": "sample", "decls": [works, branches]}],
    }}
    path = tmp_path / "sample.json"
    path.write_text(json.dumps(form), encoding="utf-8")
    oracle = yaml.safe_load((LIBRARY / "facts/valid.yaml").read_bytes())
    expected = {"branch": [oracle["branch"][1]], "work": [
        *oracle["work"], {"id": "w3", "title": "Empty", "category": "c1", "authors": []},
    ]}
    actual = facts.document(path)
    assert actual == expected
    assert type(actual["work"][0]["year"]) is int
    legacy = tmp_path / "sample.yaml"
    legacy.write_text(yaml.safe_dump(expected), encoding="utf-8")
    model = pack.read(LIBRARY)
    assert facts.load(model, path) == facts.load(model, legacy)
