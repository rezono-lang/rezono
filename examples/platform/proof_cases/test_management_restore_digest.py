"""A backup restore requires canonical payload digests in both source records."""

from hashlib import sha256
import json

import pytest

from case_support import ROOT
from management_probes import compiled
from rezono_admission import Schema, rows
from rezono_compiler import emit, facts, pack


def observations(capture_digest, readback_digest):
    return {
        "backup_trial": [{"id": "trial", "backup": "copy", "run": "run", "cluster": "recovery"}],
        "backup_capture": [{"id": "capture", "backup": "copy", "run": "run", "source_cluster": "source",
                            "payload_sha256": capture_digest}],
        "backup_readback": [{"id": "readback", "backup": "copy", "run": "run", "cluster": "recovery",
                             "trial": "trial", "source_evidence": "capture", "payload_sha256": readback_digest}],
    }


def test_restore_accepts_a_canonical_sha256():
    digest = sha256(b"synthetic payload").hexdigest()
    _, state = compiled(observations(digest, digest))
    assert state.derived["managed_backup_restored"] == {("copy", "trial")}


@pytest.mark.parametrize("digest", [
    pytest.param("same-but-not-a-digest", id="arbitrary-text"),
    pytest.param("a" * 63, id="short-hex"),
    pytest.param("a" * 65, id="long-hex"),
    pytest.param("a" * 63 + "g", id="not-hex"),
    pytest.param("A" * 64, id="uppercase"),
    pytest.param("a" * 64 + "\n", id="trailing-newline"),
])
def test_restore_refuses_equal_malformed_digests(digest):
    with pytest.raises(facts.LoadError, match="invalid SHA-256 digest") as error:
        compiled(observations(digest, digest))
    assert {diagnostic.where for diagnostic in error.value.diagnostics} == {
        "backup_capture[1].payload_sha256", "backup_readback[1].payload_sha256",
    }



def test_archived_admission_keeps_a_valid_digest_and_refuses_only_the_malformed_record():
    model = pack.read(ROOT)
    archived = Schema(json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"]))
    digest = sha256(b"synthetic payload").hexdigest()
    data = observations(digest, "same-but-not-a-digest")

    admitted, refused = rows(archived, data)

    assert admitted["backup_capture__payload_sha256"] == [("capture", digest)]
    assert "backup_readback" not in admitted
    assert "backup_readback__payload_sha256" not in admitted
    assert [r.as_dict() for r in refused] == [{
        "code": "invalid_sha256", "where": "backup_readback[1].payload_sha256", "schema": archived.sha256,
    }]
