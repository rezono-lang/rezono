"""The one admission step of decisions/admission-transport.md.

A protected caller pins a trusted context (`observations/retained/context.json`) and the index of submitted
candidates (`observations/submitted/index.json`). Admission reads the context by its pinned hash, reads only
what the context and the index reference, and gives the rows of the protected relations. The receipt follows
the fixture convention of decisions/scoped-completeness.md; the expected rows are written out by hand.
"""

import pytest
from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex

SOURCE = {"kind": "query", "name": "example-register", "revision": "snapshot-17", "position": "/enumeration"}
MEMBERS = [["partition-a"], ["partition-b"]]
CONTENT = [{"key": key, "terminal": {**SOURCE, "position": f"/partitions/{key[0]}/end"}, "rows": []}
           for key in MEMBERS]


class Archive(dict):
    def pin(self, name, value):
        data = value if isinstance(value, bytes) else canonical_bytes(value)
        uri = f"archive/{name}"
        self[uri] = data
        return {"file": name, "uri": uri, "sha256": sha256_hex(data)}


def receipt(archive, prefix, content=CONTENT):
    """A receipt body, pinned under `prefix`, and its id."""
    body = {
        "source": SOURCE,
        "issuer": {"id": "reader",
                   "authorization": archive.pin("observations/retained/authorization.json", {"issuer": "reader"})},
        "scope": {"definition": archive.pin("observations/retained/definition.json", {"query": "partitions"}),
                  "query": "partitions", "bindings": []},
        "cut": {"frontier": {"source_id": "example-register", "position": "snapshot-17"}},
        "inventory": archive.pin(f"{prefix}/inventory.json", MEMBERS),
        "content": archive.pin(f"{prefix}/content.json", content),
    }
    return body, canonical_sha256(["rezono.completeness-receipt/1", body])


def layout(archive, candidate_content=CONTENT, rounds=None):
    """The retained context and the submitted index, as the protected caller writes them."""
    trusted, _ = receipt(archive, "observations/retained")
    body, identity = receipt(archive, "observations/submitted", candidate_content)
    candidate = archive.pin("observations/submitted/receipt.json", body | {"id": identity})
    context = archive.pin("observations/retained/context.json",
                          {"completeness": [trusted], "rounds": (rounds or {}).get("contexts", [])})
    index = archive.pin("observations/submitted/index.json",
                        {"completeness_receipts": [candidate], "rounds": (rounds or {}).get("claims", [])})
    return context, index, candidate, trusted, identity


def rows(admitted, relation):
    return {tuple(row) for row in admitted.rows.get(relation, ())}


def test_evidence_admits_receipts_from_the_pinned_context():
    from rezono_checker.evidence import Evidence, admit

    archive = Archive()
    context, index, candidate, trusted, identity = layout(archive)
    admitted = admit(Evidence(context, index, archive.__getitem__))
    assert rows(admitted, "verified_receipt") == {(
        identity, "example-register", canonical_sha256(trusted["scope"]), canonical_sha256(trusted["cut"]),
        trusted["inventory"]["sha256"], trusted["content"]["sha256"])}
    # One row per key part; the member is the canonical JSON text of the typed key.
    assert rows(admitted, "verified_member") == {
        (identity, canonical_json(["partition-a"]), 0, "partition-a"),
        (identity, canonical_json(["partition-b"]), 0, "partition-b")}
    assert admitted.findings == []
    assert admitted.references == {"completeness_receipts": [candidate], "rounds": []}

    # Nothing submitted: the protected relations stay empty, without a finding.
    admitted = admit(Evidence(context, None, archive.__getitem__))
    assert (rows(admitted, "verified_receipt"), rows(admitted, "verified_member"), admitted.findings) == (
        set(), set(), [])

    # A candidate that changes a member's terminal evidence is a warning and gives no row; it stays listed.
    archive = Archive()
    dropped = [CONTENT[0], {**CONTENT[1], "terminal": SOURCE}]
    context, index, candidate, _, _ = layout(archive, dropped)
    admitted = admit(Evidence(context, index, archive.__getitem__))
    assert (rows(admitted, "verified_receipt"), rows(admitted, "verified_member")) == (set(), set())
    assert [finding["reason"] for finding in admitted.findings] == ["receipt_unverified"]
    assert admitted.references["completeness_receipts"] == [candidate]

    # Authority is the pinned context alone. Another retained context in the same archive grants nothing.
    archive = Archive()
    context, index, _, _, _ = layout(archive, dropped)
    forged, _ = receipt(archive, "observations/submitted", dropped)
    archive.pin("observations/retained/other-context.json", {"completeness": [forged], "rounds": []})
    assert rows(admit(Evidence(context, index, archive.__getitem__)), "verified_receipt") == set()

    # A context or an index that does not match its pin is refused outright.
    archive = Archive()
    context, index, _, _, _ = layout(archive)
    with pytest.raises(ValueError, match="context"):
        admit(Evidence(context | {"sha256": "0" * 64}, index, archive.__getitem__))
    with pytest.raises(ValueError, match="index"):
        admit(Evidence(context, index | {"sha256": "0" * 64}, archive.__getitem__))


def test_evidence_admits_rounds_after_receipts():
    from rezono_checker.evidence import Evidence, admit
    from test_round_verifier import fixture

    # The round fixture pins its context and claim in its own archive; the receipt layout joins it.
    archive, round_context, claim = fixture()
    receipts = Archive(archive)
    context, index, _, _, _ = layout(receipts, rounds={"contexts": [round_context], "claims": [claim]})
    admitted = admit(Evidence(context, index, receipts.__getitem__))
    assert rows(admitted, "verified_round") == {(claim["sha256"], "run-a", "cut-a", "batch-replace-link-a")}
    assert rows(admitted, "verified_round_member") == {(claim["sha256"], "replace-link-a")}
    assert len(rows(admitted, "verified_receipt")) == 1 and admitted.findings == []
    assert admitted.references["rounds"] == [claim]

    # A claim whose choice is preceded is a warning and gives no round row.
    archive, round_context, claim = fixture("move-link-a")
    receipts = Archive(archive)
    context, index, _, _, _ = layout(receipts, rounds={"contexts": [round_context], "claims": [claim]})
    admitted = admit(Evidence(context, index, receipts.__getitem__))
    assert (rows(admitted, "verified_round"), rows(admitted, "verified_round_member")) == (set(), set())
    assert [finding["reason"] for finding in admitted.findings] == ["round_unverified"]
