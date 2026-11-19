"""Typed locations in the exact schema or role listing from which an export was made."""

from hashlib import sha256
from pathlib import Path

import pytest
from linkml.validator import validate

CONTRACT = Path(__file__).resolve().parents[2] / "output-index.yaml"


def problems(field):
    return validate(field, str(CONTRACT), "OutputField").results


def test_schema_and_role_listing_are_distinct_typed_field_origins():
    for origin, file, raw, pointer in [
        ("schema", "schema.json", b'{"pack":"sample"}', "/pack"),
        ("role_listing", "index.json", b'{"objects":[{"name":"rows.json"}]}', "/objects/0/name"),
    ]:
        source = {"file": file, "sha256": sha256(raw).hexdigest(), "pointer": pointer}
        field = {"line": 2, "origin": origin, "document": source}
        assert not problems(field)
        assert problems({"line": 2, "origin": origin})
        assert problems({**field, "witness": {"relation": "point", "key": "A"}})
        assert problems({**field, "document": {**source, "pointer": "invalid"}})
        assert problems({**field, "document": {**source, "sha256": "short"}})
        other = "index.json" if file == "schema.json" else "schema.json"
        assert problems({**field, "document": {**source, "file": other}})
        assert problems({**field, "origin": "knowledge"})
