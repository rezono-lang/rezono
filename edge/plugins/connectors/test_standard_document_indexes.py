"""Schema scalar origins for three standard exports, scoped to one role's schema.json."""

import hashlib
import json

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_publication import rdf

import odcs
import shacl


SCHEMA = {"rezono": "1.0", "pack": "atlas", "base": "https://example.org/atlas/",
          "kinds": {"Point": {"id": {"type": "Text"}, "world": "closed",
                              "slots": {"label": {"type": "Text", "card": "1", "states": ["known"]}}}}}


def field(place, pointer):
    digest = hashlib.sha256(canonical_json(SCHEMA).encode()).hexdigest()
    return {**place, "origin": "schema", "document": {
        "file": "schema.json", "sha256": digest, "pointer": pointer}}


def check_file(body, record, name, expected):
    assert body == expected
    assert record["path"] == name
    assert record["sha256"] == hashlib.sha256(body).hexdigest()


def test_context_type_uses_its_slot_type():
    context = rdf.context(SCHEMA)
    assert context["@context"]["Point"]["@context"]["label"]["@type"].endswith("string")
    from rezono_publication.context_index import indexed_context

    body, record = indexed_context(SCHEMA)
    check_file(body, record, "context.jsonld", json.dumps(context, sort_keys=True, ensure_ascii=False, indent=1).encode())
    assert field({"pointer": "/@context/Point/@context/label/@type"}, "/kinds/Point/slots/label/type") in record["fields"]


def test_shape_name_uses_its_slot_declaration():
    text = shacl.to_turtle(SCHEMA)
    line, = [i for i, s in enumerate(text.splitlines(), 1) if 'sh:name "label"' in s]
    from shacl_index import indexed_shapes

    body, record = indexed_shapes(SCHEMA)
    check_file(body, record, "shapes.ttl", text.encode())
    assert field({"line": line}, "/kinds/Point/slots/label") in record["fields"]


def test_contract_name_uses_schema_pack():
    text = odcs.to_yaml(SCHEMA)
    assert yaml.safe_load(text)["name"] == "atlas"
    from odcs_index import indexed_contract

    body, record = indexed_contract(SCHEMA)
    check_file(body, record, "contract.odcs.yaml", text.encode())
    assert field({"pointer": "/name"}, "/pack") in record["fields"]


def test_distribution_uses_its_matching_listed_object():
    import dcat
    from rezono_publication import l0

    pin = {"manifest": "m-7", "dataset": "d-" + "b" * 64}
    files = {"row-json": "rows.json"}
    objects = [{"name": name, "uri": f"https://example.org/atlas/m-7/reader/publication/{name}",
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
               for name, raw in [("schema.json", canonical_json(SCHEMA).encode()), ("rows.json", b"[]")]]
    listing = {"format": "rezono.publication-form/1", "pack": "atlas", "role": "reader", **pin,
               "schema": l0.schema_id(SCHEMA), "sources": [], "objects": objects}
    raw = json.dumps(listing, indent=2).encode()
    text = dcat.to_turtle(SCHEMA, pin, files)
    line, = [i for i, s in enumerate(text.splitlines(), 1) if "accessURL" in s and "rows.json" in s]
    from dcat_index import indexed_catalogue

    body, record = indexed_catalogue(SCHEMA, pin, files, "reader", raw)
    check_file(body, record, "dcat.ttl", text.encode())
    assert {"line": line, "origin": "role_listing", "document": {
        "file": "index.json", "sha256": hashlib.sha256(raw).hexdigest(),
        "pointer": "/objects/1/name"}} in record["fields"]
    for mismatch in [{"role": "editor"}, {"manifest": "m-8"}, {"objects": objects[:1]}]:
        with pytest.raises(ValueError):
            indexed_catalogue(SCHEMA, pin, files, "reader", json.dumps({**listing, **mismatch}).encode())
