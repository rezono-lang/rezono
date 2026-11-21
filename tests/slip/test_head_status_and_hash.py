"""The head of the local reader gives the status of the witness check and the manifest's hash
(decisions/viewer-slip.md, "The role's part of the bundle"): the status only, never a check's name."""

import hashlib
import json

import pytest
from slip_support import PACK, ask, publish_main


class MissingHeadStatus(AssertionError):
    """GET /<pack>/head has no witness_check or no manifest_sha256."""


def head(store, role="reader") -> dict:
    [answer] = ask(store, role, f"/{PACK}/head")
    assert answer["status"] == 200, answer
    return answer["body"]


def test_head_status_and_hash(tmp_path):
    store, manifest = publish_main(tmp_path)
    path = store / PACK / "manifests" / f"{manifest['id']}.json"
    got = head(store)
    if "witness_check" not in got or "manifest_sha256" not in got:
        raise MissingHeadStatus(sorted(got))
    assert got["witness_check"] == "green"
    assert got["manifest_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert "rezono:proofs" not in json.dumps(got) and "checks" not in got

    # The same publication with a manifest that lists no witness check: no status, and still the hash.
    document = json.loads(path.read_bytes())
    document["checks"] = [check for check in document["checks"] if check["name"] != "rezono:proofs"]
    data = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(data)
    [head_file] = sorted((store / PACK / "heads").glob("*.json"))
    pointer = json.loads(head_file.read_bytes())
    pointer["sha256"] = hashlib.sha256(data).hexdigest()
    head_file.write_bytes(json.dumps(pointer, separators=(",", ":")).encode("utf-8"))
    without = head(store)
    assert "witness_check" not in without
    assert without["manifest_sha256"] == hashlib.sha256(data).hexdigest()
