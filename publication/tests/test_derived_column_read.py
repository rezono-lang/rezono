"""Read an independently described ordered derived tuple under its own schema."""

import json

import pytest

from rezono_canon import canonical_bytes
from rezono_publication import l0


class MissingTupleKey(AssertionError):
    """The ordinary schema reader does not admit an ordered derived relation."""


def read(schema, rows):
    body = canonical_bytes({"$schema": l0.schema_id(schema), "$rows": rows})
    return l0.read_collection(schema, json.loads(body))


@pytest.mark.xfail(strict=True, raises=MissingTupleKey,
                   reason="Read explicit derived tuple order and verify the key against typed cells.")
def test_publication_derived_column_read():
    known = {"card": "1", "states": ["known"], "derived": True}
    kinds = {
        "Stage": {"world": "closed", "id": {"type": "Text"}, "slots": {}},
        "RankedStage": {"world": "open", "id": {"type": "Text"}, "slots": {
            "stage": {"ref": "Stage"} | known,
            "count": {"type": "Integer", "min": "-9223372036854775808", "max": "9223372036854775807"} | known,
            "label": {"type": "Text"} | known,
        }},
    }
    old = {"rezono": "1.0", "pack": "example", "base": "https://example.org/example/", "kinds": kinds}
    stage = {"$kind": "Stage", "$id": "stage-a"}
    row = {"$kind": "RankedStage", "$id": '["stage-a","9007199254740993","001"]',
           "stage": {"$ref": "stage-a"}, "count": "9007199254740993", "label": "001"}
    noninteger = {"$id": '["stage-a","zero","001"]', "count": "zero"}
    assert l0.check_schema(old) == l0.schema_id(old)
    assert read(old, [stage, row]) == [stage, row]
    with pytest.raises(l0.L0Error, match=r"count.*not an integer"):
        read(old, [stage, row | noninteger])

    ranked = kinds["RankedStage"] | {"tuple_key": ["stage", "count", "label"]}
    ordered = old | {"kinds": kinds | {"RankedStage": ranked}}
    ordered = json.loads(canonical_bytes(ordered))
    assert list(ordered["kinds"]["RankedStage"]["slots"]) == ["count", "label", "stage"]
    try:
        schema_id = l0.check_schema(ordered)
    except l0.L0Error as error:
        if "tuple_key" in str(error) and "not kind members" in str(error):
            raise MissingTupleKey(str(error)) from error
        raise
    assert schema_id == l0.schema_id(ordered)
    assert read(ordered, [stage, row]) == [stage, row]

    for changed in (
        {"$id": '["stage-a","2","001"]'},
        {"$id": '["9007199254740993","001","stage-a"]'},
        {"$id": '["stage-a", "9007199254740993","001"]'},
    ):
        with pytest.raises(l0.L0Error):
            read(ordered, [stage, row | changed])
    with pytest.raises(l0.L0Error, match=r"count.*not an integer"):
        read(ordered, [stage, row | noninteger])

    for wrong in (["stage", "count"], ["stage", "count", "count"], ["stage", "count", "unknown"]):
        malformed = old | {"kinds": kinds | {"RankedStage": ranked | {"tuple_key": wrong}}}
        with pytest.raises(l0.L0Error):
            l0.check_schema(malformed)
