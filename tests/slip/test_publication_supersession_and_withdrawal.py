"""Superseded manifests stay readable with a derived standing marker and untouched bytes, while withdrawn
epochs return HTTP 410 with the withdrawal reason (decisions/publication-supersession-and-withdrawal.md)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("standing_reader.mjs")
PACK = "sample"
DEFINITION = "a" * 64
REASON = "Published with an unverified source extract."

SCHEMA = {
    "pack": {"id": PACK, "base": "https://rezono.example/sample/"},
    "kinds": [{"id": "item", "class": "Item", "world": "closed"}],
    "attributes": [
        {
            "id": "item__label",
            "kind": "item",
            "name": "label",
            "table": "item__label",
            "type": "text",
            "required": False,
        }
    ],
    "enums": [],
    "questions": [],
}


class MissingSupersessionMarker(AssertionError):
    """A superseded manifest response did not carry the derived supersession headers."""


class WithdrawnEpochNotGone(AssertionError):
    """A withdrawn epoch did not return HTTP 410 with its withdrawal reason."""


def _node_command() -> list[str]:
    node = os.environ.get("REZONO_NODE", "node")
    version = subprocess.check_output([node, "-p", "process.versions.node"], text=True).strip()
    major = int(version.split(".", 1)[0])
    return [node, "--experimental-strip-types"] if major < 24 else [node]


def _write_json(root: Path, key: str, value: object) -> tuple[Path, bytes, str]:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return path, raw, hashlib.sha256(raw).hexdigest()


def _write_object(root: Path, data: object) -> dict[str, str]:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    key = f"{PACK}/objects/{digest}.json"
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"uri": f"s3://test-store/{key}", "sha256": digest}


def _publish_epoch(root: Path, epoch: int, items: list[tuple[str, str]], base_manifest: str = "") -> tuple[Path, bytes, str]:
    bundle_key = f"{PACK}/bundles/definition.json"
    _, _, bundle_sha = _write_json(root, bundle_key, SCHEMA)
    item_obj = _write_object(root, [{"key": [item_id]} for item_id, _ in items])
    label_obj = _write_object(root, [{"key": [item_id, label]} for item_id, label in items])
    manifest_id = f"m-{epoch}"
    manifest = {
        "id": manifest_id,
        "epoch": epoch,
        "access_semantics": 2,
        "definition_sha256": DEFINITION,
        "knowledge_time": f"2026-01-0{epoch}T00:00:00Z",
        **({"base_manifest": base_manifest} if base_manifest else {}),
        "snapshots": [
            {"relation": "item", "role": "reader", "complete": False, "full": True, "format": "json", **item_obj},
            {"relation": "item__label", "role": "reader", "complete": False, "full": True, "format": "json", **label_obj},
        ],
        "compiled": [
            {"file": "bundle/schema-bundle.json", "uri": f"s3://test-store/{bundle_key}", "sha256": bundle_sha},
        ],
    }
    manifest_path, manifest_bytes, manifest_sha = _write_json(root, f"{PACK}/manifests/{manifest_id}.json", manifest)
    head_key = f"{PACK}/heads/{10**19 - 1 - epoch:019d}.json"
    _write_json(root, head_key, {"format": "rezono.head/1", "manifest": manifest_id, "epoch": epoch, "sha256": manifest_sha})
    return manifest_path, manifest_bytes, manifest_sha


def _query(root: Path, role: str, *paths: str) -> list[dict]:
    run = subprocess.run(
        [*_node_command(), str(PROBE)],
        input=json.dumps({"store": root.as_posix(), "role": role, "requests": list(paths)}),
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        cwd=ROOT,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def test_superseded_manifest_remains_readable_with_marker_and_untouched_bytes(tmp_path):
    m1_path, m1_before, m1_sha = _publish_epoch(tmp_path, 1, [("a", "alpha")])
    _publish_epoch(tmp_path, 2, [("a", "alpha"), ("b", "beta")], base_manifest="m-1")

    # Old manifest bytes are never modified and never carry a stored superseded flag.
    m1_after = m1_path.read_bytes()
    assert m1_after == m1_before
    assert hashlib.sha256(m1_after).hexdigest() == m1_sha
    assert b"superseded" not in m1_after

    replies = _query(
        tmp_path,
        "reader",
        f"/{PACK}/manifests/m-1",
        f"/{PACK}/head?m=m-1",
        f"/{PACK}/m-1/snapshots/item",
        f"/{PACK}/head",
    )
    for old_reply in replies[:3]:
        assert old_reply["status"] == 200, old_reply
        headers = old_reply["headers"]
        if headers.get("x-rezono-standing") != "superseded":
            raise MissingSupersessionMarker(json.dumps(old_reply, sort_keys=True))
        assert headers.get("x-rezono-superseded-by") == "m-2", headers
        assert f'</{PACK}/manifests/m-2>; rel="successor-version"' in headers.get("link", ""), headers

    current_reply = replies[3]
    assert current_reply["status"] == 200, current_reply
    assert current_reply["body"]["id"] == "m-2"
    assert current_reply["headers"].get("x-rezono-standing") == "current"
    assert "x-rezono-superseded-by" not in current_reply["headers"]


def test_withdrawn_epoch_returns_http_410_with_reason(tmp_path):
    m1_path, m1_before, _ = _publish_epoch(tmp_path, 1, [("a", "alpha")])
    _publish_epoch(tmp_path, 2, [("a", "alpha"), ("b", "beta")], base_manifest="m-1")

    withdrawal = {
        "format": "rezono.withdrawal/1",
        "id": "wd-2026-01",
        "state": "withdrawn",
        "decider": ["board"],
        "decided_on": "2026-02-01",
        "reason": REASON,
        "epochs": ["m-1"],
    }
    _write_json(tmp_path, f"{PACK}/withdrawals/wd-2026-01.json", withdrawal)

    # Recording a withdrawal leaves the withdrawn manifest untouched on disk.
    assert m1_path.read_bytes() == m1_before

    replies = _query(
        tmp_path,
        "reader",
        f"/{PACK}/manifests/m-1",
        f"/{PACK}/head?m=m-1",
        f"/{PACK}/m-1/snapshots/item",
        f"/{PACK}/manifests/m-2",
    )
    for withdrawn_reply in replies[:3]:
        if withdrawn_reply["status"] != 410:
            raise WithdrawnEpochNotGone(json.dumps(withdrawn_reply, sort_keys=True))
        assert withdrawn_reply["headers"].get("x-rezono-standing") == "withdrawn"
        assert withdrawn_reply["body"] == {
            "error": "withdrawn",
            "reason": REASON,
            "withdrawal": {
                "id": "wd-2026-01",
                "decider": ["board"],
                "decided_on": "2026-02-01",
                "reason": REASON,
            },
        }

    current_reply = replies[3]
    assert current_reply["status"] == 200, current_reply
    assert current_reply["body"]["id"] == "m-2"
    assert current_reply["headers"].get("x-rezono-standing") == "current"
