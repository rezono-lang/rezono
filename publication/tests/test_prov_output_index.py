"""The PROV activity name and its indexed conclusion identify the same witness."""

import hashlib
import json

import pytest


def test_proof_activity_lines_bind_their_own_conclusions():
    from rezono_publication.prov_index import indexed_prov

    proofs = [{"conclusion": {"relation": "parcel", "key": json.dumps([name])},
               "rule_id": "rule.parcel", "premises": []} for name in ("amber", "violet")]
    for selected in (proofs, proofs[:1]):
        body, record = indexed_prov("m-7", "d-" + "e" * 64, selected)
        assert record["path"] == "prov.ttl"
        assert record["sha256"] == hashlib.sha256(body).hexdigest()
        lines = body.decode("utf-8").splitlines()
        for proof in proofs:
            canonical = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode("ascii")
            digest = hashlib.sha256(canonical).hexdigest()
            activity = f"<rezono:w/{digest}> a prov:Activity"
            places = [i for i, text in enumerate(lines, 1) if text.startswith(activity)]
            fields = [f for f in record["fields"] if f.get("witness") == proof["conclusion"]]
            if proof in selected:
                line, = places
                assert {"line": line, "origin": "knowledge", "witness": proof["conclusion"]} in fields
            else:
                assert not places and not fields
                assert digest.encode("ascii") not in body
