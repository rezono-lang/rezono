"""End-to-end canonical witness IRIs in published role forms, view.ttl, prov.ttl, and
exports.index.json (decisions/publication-conclusion-addresses.md §2 and §5).

Publishes a minimal neutral pack with one derived relation (`flagged`) via `batch.epoch` and
`publish.publish(..., forms=True)` and asserts that `rows.json` `$why["$id"]`, `view.ttl`
`rd:why`, `prov.ttl` `prov:Activity` / `prov:Bundle`, `exports.index.json`, and
`edge/plugins/connectors/accept.py` all use and accept the exact canonical `<base>witness/<H>`
IRI rather than opaque `rezono:w/<H>`.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import PROV, RDF

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from rezono_canon import canonical_sha256
from rezono_publication import rdf
from rezono_publisher import batch, forms, publish, store

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
BASE_IRI = "https://rezono.example/witness-iri/"

SCHEMA = f"""id: {BASE_IRI}model
name: witness_iri
in_language: en
imports: [linkml:types]
default_range: string
annotations: {{layer: facts}}
classes:
  Item:
    attributes:
      id: {{identifier: true}}
      label: {{}}
"""

RULES = """.decl flagged(item: symbol)
flagged(x) :- item(x).
.output flagged

.decl may_read(role: symbol, kind: symbol, id: symbol)
may_read("reader", "item", x) :- item(x).
"""


def _make_pack(root: Path) -> Path:
    root.mkdir()
    (root / "pack.yaml").write_text(
        f'name: witness-iri\nversion: "1"\ndefault_language: nl\niri:\n  base: {BASE_IRI}\n',
        encoding="utf-8",
        newline="\n",
    )
    shutil.copytree(MINIMAL / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8", newline="\n")
    (root / "labels").mkdir()
    (root / "labels" / "nl.yaml").write_text("item: Item\n", encoding="utf-8", newline="\n")
    for folder, filename, content in (
        ("schema", "model.yaml", SCHEMA),
        ("rules", "rules.dl", RULES),
        ("facts", "items.yaml", "item: [{id: anchor, label: first}]\n"),
        ("facts", "items.sources.yaml", "default: {kind: tool, name: Seed, position: run-1}\n"),
    ):
        (root / folder).mkdir(exist_ok=True)
        (root / folder / filename).write_text(content, encoding="utf-8", newline="\n")
    return root


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/publication-conclusion-addresses.md: Pass schema to witness_uri in "
        "publication/rezono_publication/publication.py:328, edge/publisher/rezono_publisher/forms.py "
        "(witness lookup, prov.ttl bundle and witness_to_prov), export_index.py, and "
        "edge/plugins/connectors/accept.py so rows.json $why, view.ttl, prov.ttl, and "
        "exports.index.json emit and verify the full canonical <base>witness/<H> IRI matching "
        "the gate instead of rezono:w/<H>."
    ),
)
def test_published_role_forms_and_prov_emit_canonical_witness_iri(tmp_path: Path):
    st = store.FileStore(tmp_path / "store")
    ep = batch.epoch(_make_pack(tmp_path / "pack"), epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
    manifest = publish.publish(ep, st, {"checker": "complete", "reader": "may_read"}, forms=True)

    prefix = forms.prefix(ep.pack, manifest["id"], "reader")
    index_bytes = st.get(prefix + "index.json")
    assert index_bytes is not None
    listing = json.loads(index_bytes)
    data = {o["name"]: st.get(prefix + o["name"]) for o in listing["objects"]}
    data["index.json"] = index_bytes

    schema = json.loads(data["schema.json"])
    assert schema["base"] == BASE_IRI
    rows = json.loads(data["rows.json"])["$rows"]
    flagged_rows = [r for r in rows if r["$kind"] == "Flagged"]
    assert len(flagged_rows) == 1, rows

    # Load the role's published witness object from the manifest and compute its canonical IRI.
    w_ref = next(entry for entry in manifest["witnesses"] if entry["role"] == "reader")
    w_key = forms.key_of(w_ref["uri"])
    role_witnesses = json.loads(st.get(w_key))["witnesses"]
    flagged_witness = next(w for w in role_witnesses if w["conclusion"]["relation"] == "flagged")
    digest = canonical_sha256(flagged_witness)
    expected_iri = f"{BASE_IRI}witness/{digest}"
    assert expected_iri == rdf.canonical_witness_iri(schema, flagged_witness)

    # 1. rows.json $why carries the full canonical <base>witness/<H> IRI (rejecting rezono:w/<H>).
    why_iri = flagged_rows[0]["$why"]["$id"]
    assert why_iri == expected_iri, f"expected canonical witness IRI {expected_iri!r}, got {why_iri!r}"
    assert not why_iri.startswith("rezono:w/"), why_iri

    # 2. view.ttl binds rd:why to the canonical witness IRI, with zero rezono:w/ URIs.
    view_text = data["view.ttl"].decode("utf-8")
    assert "rezono:w/" not in view_text, view_text
    g_view = Graph().parse(data=view_text, format="turtle")
    why_objects = set(g_view.objects(None, rdf.RD.why))
    assert URIRef(expected_iri) in why_objects, why_objects

    # 3. prov.ttl uses the canonical witness IRI as prov:Activity and <base>m-1@<dataset> as prov:Bundle.
    prov_text = data["prov.ttl"].decode("utf-8")
    assert "rezono:w/" not in prov_text, prov_text
    g_prov = Graph().parse(data=prov_text, format="turtle")
    expected_bundle = URIRef(f"{BASE_IRI}{manifest['id']}@{listing['dataset']}")
    assert (expected_bundle, RDF.type, PROV.Bundle) in g_prov
    assert (URIRef(expected_iri), RDF.type, PROV.Activity) in g_prov
    assert rdf.prov_to_witness(g_prov, schema=schema) == flagged_witness

    # 4. exports.index.json indexes the prov.ttl knowledge lines citing the derived conclusion.
    exp_index = json.loads(data["exports.index.json"])
    prov_entry = next(f for f in exp_index["files"] if f["path"] == "prov.ttl")
    assert any(
        field.get("origin") == "knowledge" and field.get("witness") == flagged_witness["conclusion"]
        for field in prov_entry["fields"]
    ), prov_entry

    # 5. Independent connector verifier accepts view.ttl and prov.ttl with canonical witness IRIs.
    spec = importlib.util.spec_from_file_location(
        "rezono_accept_witness_iri", ROOT / "edge" / "plugins" / "connectors" / "accept.py"
    )
    assert spec is not None and spec.loader is not None
    accept = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(accept)
    report = accept.published(data, st.uri(prefix))
    assert report["view.ttl"]["state"] == "accepted", report["view.ttl"]
    assert report["prov.ttl"]["state"] == "accepted", report["prov.ttl"]
