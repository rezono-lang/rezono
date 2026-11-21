"""End-to-end canonical witness IRI check: Python publisher -> local gate -> rdf.canonical_witness_iri oracle.

Verifies that every witness served by `edge/gate/src/local.ts` on a publisher-built store carries
the exact canonical IRI `<base>witness/<H(witness)>` computed by `rezono_publication.rdf.canonical_witness_iri`
(never standalone `rezono:w/<hash>`), enforces role isolation, and does not fabricate `load_bearing` in the gate.
"""

from __future__ import annotations

from rezono_publication import rdf
from slip_support import PACK, ask, publish_main, row_query


def test_local_gate_witness_iris_match_python_rdf_oracle_and_enforce_roles(tmp_path):
    store, manifest = publish_main(tmp_path)
    mid = manifest["id"]

    # Fetch the reader's bundle to obtain the exact pack base IRI used by the publication.
    [bundle_res] = ask(store, "reader", f"/{PACK}/bundle?m={mid}")
    assert bundle_res["status"] == 200, bundle_res
    pack_id = bundle_res["body"]["pack"]["id"]
    base = bundle_res["body"]["pack"].get("base") or f"https://rezono.example/{pack_id}/"
    schema = {"rezono": "1.0", "pack": pack_id, "base": base, "kinds": {}}

    # Reader asks grounds for a shared conclusion (`flagged`) and a restricted conclusion (`linked`).
    flagged_path = f"/{PACK}/{mid}/ask/grounds?{row_query('flagged', 'item-a', '12')}"
    linked_path = f"/{PACK}/{mid}/ask/grounds?{row_query('linked', 'item-a', 'link-a')}"
    reader_flagged, reader_linked = ask(store, "reader", flagged_path, linked_path)
    assert reader_flagged["status"] == 200, reader_flagged
    assert reader_linked["status"] == 200, reader_linked

    for res in (reader_flagged, reader_linked):
        body = res["body"]
        assert len(body["witnesses"]) >= 1
        for w in body["witnesses"]:
            iri = w["iri"]
            assert iri.startswith(f"{base}witness/"), f"expected canonical <base>witness/<H>, got {iri}"
            assert not iri.startswith("rezono:w/"), f"production gate must not emit standalone rezono:w/: {iri}"
            raw_witness = {k: v for k, v in w.items() if k != "iri"}
            assert iri == rdf.canonical_witness_iri(schema, raw_witness)
        for step in body["steps"]:
            assert "load_bearing" not in step, "gate must not fabricate load_bearing"

    # Restricted role `summary` reads `flagged` with the same canonical witness IRI, and gets 404 on `linked`.
    summary_flagged, summary_linked = ask(store, "summary", flagged_path, linked_path)
    assert summary_flagged["status"] == 200, summary_flagged
    assert summary_linked["status"] == 404, summary_linked
    assert [w["iri"] for w in summary_flagged["body"]["witnesses"]] == [
        w["iri"] for w in reader_flagged["body"]["witnesses"]
    ]
