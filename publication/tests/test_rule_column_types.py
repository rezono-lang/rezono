"""The role's publication keeps the scalar types of a checked derived relation."""

import pytest

from rezono_publication import arrow, l0, publication, rdf


def test_derived_columns_preserve_exact_keys_and_scalar_types():
    relation = {"id": "example", "world": "closed", "columns": [
        {"name": "label", "type": "string"}, {"name": "number", "type": "integer"},
    ]}
    bundle = {"pack": {"id": "toy"}, "kinds": [], "relations": [relation]}
    snapshots = {"example": [("001", "9007199254740993")]}
    schema, plan = publication.schema_document(bundle, full=set())
    assert schema["kinds"]["Example"]["world"] == "open"
    assert schema["kinds"]["Example"]["tuple_key"] == ["label", "number"]
    assert {name: slot["type"] for name, slot in schema["kinds"]["Example"]["slots"].items()} == {
        "label": "Text", "number": "Integer",
    }
    rows = publication.row_json(schema, plan, {"rows": snapshots, "witnesses": [], "sources": []})
    assert rows == [{"$kind": "Example", "$id": '["001","9007199254740993"]',
                     "label": "001", "number": "9007199254740993"}]
    l0.check_schema(schema)
    assert l0.read_rows(schema, rows) == rows
    assert publication.differences(schema, plan, rows, snapshots) == []
    assert arrow.from_arrow(schema, arrow.to_arrow(schema, rows)) == rows
    assert rdf.from_graph(schema, rdf.to_graph(schema, rows)) == rows
    with pytest.raises(l0.L0Error, match="number.*not an integer"):
        l0.read_rows(schema, [rows[0] | {"$id": '["001","zero"]', "number": "zero"}])

    for untyped in ({"name": "number"}, {"name": "number", "type": "rational"}, {"name": "number", "type": "float"}):
        relation["columns"][-1] = untyped
        with pytest.raises(publication.FormError, match=r"example\.number: unsupported rule column type"):
            publication.schema_document(bundle)
