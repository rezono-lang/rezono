"""Canonical IRIs, epoch/hash pins, and single-row resolution for derived conclusions and witnesses
(decisions/publication-conclusion-addresses.md)."""

import pytest
from rdflib import URIRef
from rdflib.namespace import PROV, RDF

from rezono_canon import canonical_sha256
from rezono_publication import l0, rdf
from rezono_publication import publication
from rezono_publication.hash import hashes

SCHEMA = {
    "rezono": "1.0",
    "pack": "sample",
    "base": "https://rezono.example/sample/",
    "types": {
        "Score": {"of": "Integer", "min": "0", "max": "1000"},
    },
    "kinds": {
        "Item": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {},
        },
        "ItemScore": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {
                "item": {"ref": "Item", "card": "1", "states": ["known"], "derived": True},
                "score": {"type": "Score", "card": "1", "states": ["known"], "derived": True},
            },
        },
    },
}


def _rows(scores: dict[str, int], why: dict[str, str] | None = None) -> list[dict]:
    out = [{"$kind": "Item", "$id": item_id} for item_id in sorted(scores)]
    for item_id in sorted(scores):
        row = {
            "$kind": "ItemScore",
            "$id": item_id,
            "item": {"$ref": item_id},
            "score": scores[item_id],
        }
        if why and item_id in why:
            row["$why"] = {"$id": why[item_id]}
        out.append(row)
    return out


def _witness(item_id: str) -> dict:
    return {
        "conclusion": {"relation": "item_score", "key": f'["{item_id}"]'},
        "rule_id": "rule.item_score",
        "premises": [
            {"row": {"relation": "item", "key": f'["{item_id}"]'}, "polarity": "positive", "stratum": 0},
        ],
    }


def test_same_derived_row_across_two_epochs_keeps_iri_with_different_pin():
    assert l0.check_schema(SCHEMA) == l0.schema_id(SCHEMA)
    epoch_1 = _rows({"item-1": 10})
    epoch_2 = _rows({"item-1": 20})
    d1 = hashes(SCHEMA, epoch_1)["dataset"]
    d2 = hashes(SCHEMA, epoch_2)["dataset"]
    assert d1 != d2

    iri_1 = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1")
    iri_2 = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1")
    assert iri_1 == iri_2 == "https://rezono.example/sample/ItemScore/item-1"

    pinned_1 = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1", manifest="m-1", dataset=d1)
    pinned_2 = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1", manifest="m-2", dataset=d2)
    assert pinned_1 == f"https://rezono.example/sample/ItemScore/item-1?pin=m-1@{d1}"
    assert pinned_2 == f"https://rezono.example/sample/ItemScore/item-1?pin=m-2@{d2}"
    assert pinned_1 != pinned_2

    base_1, pin_1 = rdf.parse_pin(pinned_1)
    base_2, pin_2 = rdf.parse_pin(pinned_2)
    assert base_1 == base_2 == iri_1
    assert pin_1 == {"manifest": "m-1", "dataset": d1}
    assert pin_2 == {"manifest": "m-2", "dataset": d2}
    assert rdf.parse_pin(iri_1) == (iri_1, None)

    # Hash-only pin is accepted; epoch pin without hash pin is refused (L0 §6.4).
    hash_only = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1", dataset=d1)
    assert rdf.parse_pin(hash_only) == (iri_1, {"dataset": d1})
    with pytest.raises(l0.L0Error):
        rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1", manifest="m-1")
    with pytest.raises(l0.L0Error):
        rdf.parse_pin(f"{iri_1}?pin=m-1")

    # Segment spelling follows L0 §3.4 just like element IRIs.
    assert rdf.conclusion_iri(SCHEMA, "ItemScore", "a/b c") == "https://rezono.example/sample/ItemScore/a~2Fb~20c"


def test_conclusion_and_witness_iris_resolve_to_one_row_and_match_rdf_and_prov():
    w1 = _witness("item-1")
    w2 = _witness("item-2")

    c1_iri = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1")
    w1_iri = rdf.canonical_witness_iri(SCHEMA, w1)
    w2_iri = rdf.canonical_witness_iri(SCHEMA, w2)
    assert w1_iri == f"https://rezono.example/sample/witness/{canonical_sha256(w1)}"
    assert w1_iri != w2_iri

    rows = _rows({"item-1": 10, "item-2": 20}, why={"item-1": w1_iri, "item-2": w2_iri})
    row_1 = next(r for r in rows if r["$kind"] == "ItemScore" and r["$id"] == "item-1")
    d1 = hashes(SCHEMA, rows)["dataset"]

    # RDF view uses the canonical conclusion IRI as subject and the canonical witness IRI in rd:why.
    g_rdf = rdf.to_graph(SCHEMA, rows)
    assert (URIRef(c1_iri), RDF.type, URIRef("https://rezono.example/sample/ItemScore")) in g_rdf
    why_targets = {
        g_rdf.value(stmt, rdf.RD.why)
        for stmt in g_rdf.subjects(RDF.type, RDF.Statement)
        if g_rdf.value(stmt, RDF.subject) == URIRef(c1_iri)
    }
    assert URIRef(w1_iri) in why_targets

    # PROV-O output under the same schema uses the exact same canonical conclusion and witness IRIs.
    g_prov = rdf.witness_to_prov(w1, "m-1", d1, schema=SCHEMA)
    assert str(g_prov.identifier) == f"https://rezono.example/sample/m-1@{d1}"
    assert (g_prov.identifier, RDF.type, PROV.Bundle) in g_prov
    assert (URIRef(w1_iri), RDF.type, PROV.Activity) in g_prov
    assert (URIRef(c1_iri), RDF.type, PROV.Entity) in g_prov
    assert (URIRef(c1_iri), PROV.wasGeneratedBy, URIRef(w1_iri)) in g_prov
    assert (URIRef(w1_iri), PROV.used, URIRef("https://rezono.example/sample/Item/item-1")) in g_prov
    assert rdf.prov_to_witness(g_prov, schema=SCHEMA) == w1

    # Both conclusion IRIs and witness IRIs (unpinned and pinned) resolve back to exactly one row.
    c1_pinned = rdf.conclusion_iri(SCHEMA, "ItemScore", "item-1", manifest="m-1", dataset=d1)
    w1_pinned = rdf.canonical_witness_iri(SCHEMA, w1, manifest="m-1", dataset=d1)
    assert rdf.resolve_iri(SCHEMA, rows, c1_iri) == row_1
    assert rdf.resolve_iri(SCHEMA, rows, c1_pinned, manifest="m-1", dataset=d1) == row_1
    assert rdf.resolve_iri(SCHEMA, rows, w1_iri, witnesses=[w1, w2]) == row_1
    assert rdf.resolve_iri(SCHEMA, rows, w1_pinned, witnesses=[w1, w2], manifest="m-1", dataset=d1) == row_1

    # Mismatched pins or unknown IRIs are refused.
    with pytest.raises(l0.L0Error):
        rdf.resolve_iri(SCHEMA, rows, c1_pinned, manifest="m-2", dataset=d1)
    with pytest.raises(l0.L0Error):
        rdf.resolve_iri(SCHEMA, rows, rdf.conclusion_iri(SCHEMA, "ItemScore", "missing"))
    with pytest.raises(l0.L0Error):
        rdf.resolve_iri(SCHEMA, rows, f"https://rezono.example/sample/witness/{'0' * 64}", witnesses=[w1, w2])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/publication-conclusion-addresses.md: Pass schema doc to witness_uri in "
        "publication/rezono_publication/publication.py:328 (and align edge/publisher/rezono_publisher/forms.py, "
        "export_index.py, and edge/plugins/connectors/accept.py) so $why in row_json and publication.form "
        "emits the full canonical <base>witness/<H> IRI matching the gate instead of rezono:w/<H>."
    ),
)
def test_publication_row_json_and_form_emit_canonical_witness_iri_in_why():
    """One witness, one IRI: row_json and publication.form emit `<base>witness/<H>` in `$why`
    (never `rezono:w/<H>`), following the schema's `base` and resolving back to the single row."""
    witness = {
        "conclusion": {"relation": "item_flag", "key": '["item-1","ready"]'},
        "rule_id": "rule.item_flag",
        "premises": [
            {"row": {"relation": "item", "key": '["item-1"]'}, "polarity": "positive", "stratum": 0},
        ],
    }
    digest = canonical_sha256(witness)
    legacy_uri = f"rezono:w/{digest}"
    raw_rows = {"item": [("item-1",)], "item_flag": [("item-1", "ready")]}
    manifest = {
        "id": "m-1",
        "epoch": 1,
        "knowledge_time": "2026-01-01T00:00:00Z",
        "definition_sha256": "a" * 64,
    }

    for pack_id, base_iri in (
        ("sample", "https://rezono.example/sample/"),
        ("other", "https://other.example/alt/"),
    ):
        bundle = {
            "pack": {"id": pack_id, "base": base_iri},
            "kinds": [{"id": "item", "class": "Item", "world": "closed"}],
            "attributes": [],
            "arrows": [],
            "relations": [
                {
                    "id": "item_flag",
                    "world": "closed",
                    "columns": [
                        {"name": "item", "type": "string"},
                        {"name": "status", "type": "string"},
                    ],
                }
            ],
        }
        doc, plan = publication.schema_document(bundle, full=None)
        assert doc["base"] == base_iri
        expected_iri = f"{base_iri}witness/{digest}"
        assert expected_iri == rdf.canonical_witness_iri(doc, witness)

        out = publication.row_json(doc, plan, {"rows": raw_rows, "witnesses": [witness], "sources": []})
        derived_row = next(r for r in out if r["$kind"] == "ItemFlag")
        why_iri = derived_row["$why"]["$id"]
        assert why_iri == expected_iri, f"expected full canonical witness IRI {expected_iri!r}, got {why_iri!r}"
        assert why_iri != legacy_uri and not why_iri.startswith("rezono:w/"), why_iri

        # publication.form produces the same canonical witness IRI and passes L0 validation.
        built = publication.form(manifest, bundle, raw_rows, None, [witness], [], "reader")
        l0.read_rows(built["schema"], built["rows"])
        form_row = next(r for r in built["rows"] if r["$kind"] == "ItemFlag")
        assert form_row["$why"]["$id"] == expected_iri

        # RDF view binds rd:why to the canonical witness IRI (never rezono:w/<H>), and resolve_iri finds the row.
        g_rdf = rdf.to_graph(doc, out)
        why_objects = set(g_rdf.objects(None, rdf.RD.why))
        assert URIRef(expected_iri) in why_objects
        assert URIRef(legacy_uri) not in why_objects
        assert rdf.resolve_iri(doc, out, why_iri, witnesses=[witness]) == derived_row

