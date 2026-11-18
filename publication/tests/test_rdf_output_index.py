"""Row identity at the RDF export boundary, as specified in decisions/standard-export-index.md."""

import hashlib
import json
from pathlib import Path

import pytest

from rezono_publication import rdf


def test_rdf_subject_lines_point_to_their_source_rows():
    from rezono_publication.rdf_index import indexed_view

    cases = Path(__file__).resolve().parents[2] / "docs/publication/cases"
    schema = json.loads((cases / "fixture.schema.json").read_text("utf-8"))
    rows = [{"$kind": "Host", "$id": name, "memory_need": {"$unknown": ""},
             "owner": {"$na": ""}, "tags": []} for name in ("amber", "violet")]
    refs = {("Host", "amber"): {"relation": "inventory", "key": '["A",2]'},
            ("Host", "violet"): {"relation": "inventory", "key": '["V",1]'}}
    body, record = indexed_view(schema, rows, refs)
    assert body == rdf.to_turtle(schema, rows).encode("utf-8")
    assert record["path"] == "view.ttl"
    assert record["sha256"] == hashlib.sha256(body).hexdigest()
    lines = body.decode("utf-8").splitlines()
    for (_, name), source in refs.items():
        subject = f"<https://rezono.example/fixture/Host/{name}> a "
        line, = [i for i, text in enumerate(lines, 1) if text.startswith(subject)]
        assert {"line": line, "origin": "knowledge", "witness": source} in record["fields"]
    with pytest.raises(ValueError, match="violet"):
        indexed_view(schema, rows, {("Host", "amber"): refs["Host", "amber"]})
