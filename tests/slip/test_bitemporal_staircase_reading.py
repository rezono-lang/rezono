"""Standard bitemporal staircase reading of `std-time` served through the local gate
(decisions/bitemporal-staircase-reading.md).

A neutral, domain-free pack binds `packs/std-time` via `is_a: Interval` without declaring any
`staircases` reading of its own in `channels.yaml`, and publishes two consecutive main epochs:
- `m-1` (`2026-01-10T00:00:00Z`): interval `cov-a` has `start: 10`, no `end` recorded yet
  (open-world unknown at both reference points `p1` and `p2`).
- `m-2` (`2026-02-10T00:00:00Z`): `cov-a`'s `end: 16` is now recorded, turning `p1` (12) to
  `positive` (`end_beyond_horizon`) and `p2` (18) to `negative` (`ended`).

The compiled bundle must inherit `std-time`'s default staircase reading, and `edge/gate/src/local.ts`
must serve `GET /bound-time/m-2/readings/staircase?subject=cov-a` as `rezono.staircase/1` with
verified cells, explicit unknown/known states, canonical `<base>witness/<H>` IRIs matching the
published role witnesses, and role-scoped `404` non-disclosure for an unauthorized role.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from rezono_canon import canonical_sha256
from rezono_compiler import modules
from rezono_publisher import batch, publish, store
from slip_support import ask

ROOT = Path(__file__).resolve().parents[2]
THEORY = ROOT / "packs" / "std-time"
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
PACK_NAME = "bound-time"
BASE_IRI = "https://rezono.example/bound-time/"
ROLES = {"checker": "complete", "reader": "may_read", "other": "may_read"}

ACCESS_RULES = """.decl may_read(role: symbol, kind: symbol, element: symbol)
.decl may_read_full(role: symbol, kind: symbol)
may_read("reader", "axis", x) :- axis(x).
may_read("reader", "reference_point", x) :- reference_point(x).
may_read("reader", "interval", x) :- interval(x).
may_read("reader", "coverage", x) :- coverage(x).
may_read_full("reader", "axis") :- axis(_).
may_read_full("reader", "reference_point") :- reference_point(_).
may_read_full("reader", "interval") :- interval(_).
may_read_full("reader", "coverage") :- coverage(_).
may_read("other", "axis", x) :- axis(x).
may_read("other", "reference_point", x) :- reference_point(x).
may_read("other", "coverage", "cov-b") :- coverage("cov-b").
"""


def _write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8", newline="\n")


def _make_bound_pack(root: Path, coverages: list[dict]) -> Path:
    theory_copy = root / "std-time"
    if not theory_copy.exists():
        shutil.copytree(THEORY, theory_copy)
    pack_dir = root / PACK_NAME
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    for folder in ("schema", "labels", "facts", "rules"):
        (pack_dir / folder).mkdir(parents=True)
    shutil.copytree(MINIMAL / "messages", pack_dir / "messages")
    (pack_dir / "messages" / "en.mf2").write_text(
        (pack_dir / "messages" / "nl.mf2").read_text(encoding="utf-8").replace("@locale nl", "@locale en", 1),
        encoding="utf-8",
        newline="\n",
    )
    _write_yaml(
        pack_dir / "pack.yaml",
        {
            "name": PACK_NAME,
            "version": "0.1.0",
            "default_language": "en",
            "iri": {"base": BASE_IRI},
            "imports": [
                {
                    "name": "std-time",
                    "path": "../std-time",
                    "sha256": modules.pack_hash(theory_copy),
                }
            ],
        },
    )
    _write_yaml(
        pack_dir / "schema" / "bound.yaml",
        {
            "id": BASE_IRI + "bound",
            "name": "bound_time",
            "in_language": "en",
            "prefixes": {"linkml": "https://w3id.org/linkml/"},
            "imports": ["linkml:types", "std-time:time"],
            "default_range": "string",
            "annotations": {"layer": "facts"},
            "classes": {
                "Coverage": {
                    "is_a": "Interval",
                    "attributes": {"title": {}},
                }
            },
        },
    )
    for lang in ("en", "nl"):
        (pack_dir / "labels" / f"{lang}.yaml").write_text(
            "coverage: Coverage\ncoverage.title: Title\n", encoding="utf-8", newline="\n"
        )
    # Intentionally declares NO `staircases:` of its own: must inherit std-time's default reading.
    (pack_dir / "channels.yaml").write_text(
        "kinds:\n  - {kind: coverage, shape: rect}\n", encoding="utf-8", newline="\n"
    )
    (pack_dir / "rules" / "access.dl").write_text(ACCESS_RULES, encoding="utf-8", newline="\n")
    _write_yaml(
        pack_dir / "facts" / "state.yaml",
        {
            "axis": [{"id": "timeline"}],
            "reference_point": [
                {"id": "p1", "on_axis": "timeline", "position": 12, "horizon": 0},
                {"id": "p2", "on_axis": "timeline", "position": 18, "horizon": 0},
            ],
            "coverage": coverages,
        },
    )
    _write_yaml(
        pack_dir / "facts" / "state.sources.yaml",
        {"default": {"kind": "tool", "name": "Register", "position": "snapshot"}},
    )
    return pack_dir


def _witness_hashes(store_dir: Path, manifest_id: str, role: str) -> set[str]:
    manifest = json.loads((store_dir / PACK_NAME / "manifests" / f"{manifest_id}.json").read_text(encoding="utf-8"))
    ref = next(entry for entry in manifest.get("witnesses") or [] if entry["role"] == role)
    key = ref["uri"].split("://", 1)[1].split("/", 1)[1]
    payload = json.loads((store_dir / key).read_text(encoding="utf-8"))
    all_witnesses = list(payload.get("witnesses") or []) + list(payload.get("calc_witnesses") or [])
    return {canonical_sha256(w) for w in all_witnesses}


def test_std_time_bound_pack_serves_bitemporal_staircase_reading_via_gate(tmp_path: Path):
    st_dir = tmp_path / "store"
    st = store.FileStore(st_dir)

    # Epoch 1 (2026-01-10): cov-a has start=10 and no recorded end -> unknown (end_not_recorded) at p1 and p2.
    p1 = _make_bound_pack(
        tmp_path / "work-1",
        [
            {"id": "cov-a", "title": "A", "on_axis": "timeline", "start": 10, "known_from": 5},
            {"id": "cov-b", "title": "B", "on_axis": "timeline", "start": 10, "end": 20, "known_from": 5},
        ],
    )
    ep1 = batch.epoch(p1, epoch=1, knowledge_time="2026-01-10T00:00:00Z", sources=[("rules", "e1")])
    m1 = publish.publish(ep1, st, ROLES)
    assert m1["id"] == "m-1"

    # Epoch 2 (2026-02-10): cov-a gains end=16 -> positive at p1 (12) and negative at p2 (18).
    p2 = _make_bound_pack(
        tmp_path / "work-2",
        [
            {"id": "cov-a", "title": "A", "on_axis": "timeline", "start": 10, "end": 16, "known_from": 5},
            {"id": "cov-b", "title": "B", "on_axis": "timeline", "start": 10, "end": 20, "known_from": 5},
        ],
    )
    ep2 = batch.epoch(p2, epoch=2, knowledge_time="2026-02-10T00:00:00Z", sources=[("rules", "e2")])
    m2 = publish.publish(ep2, st, ROLES)
    assert m2["id"] == "m-2"

    # Sanity check: the local gate already serves head and bundle for the published std-time pack.
    head_resp, bundle_resp, reading_resp = ask(
        st_dir,
        "reader",
        f"/{PACK_NAME}/head",
        f"/{PACK_NAME}/bundle",
        f"/{PACK_NAME}/m-2/readings/staircase?subject=cov-a",
    )
    assert head_resp["status"] == 200 and head_resp["body"]["id"] == "m-2", head_resp
    assert bundle_resp["status"] == 200, bundle_resp

    # 1. Bundle inherits std-time's default staircase reading without the domain declaring `staircases:`.
    staircases = (bundle_resp["body"].get("channels") or {}).get("staircases") or []
    assert any(entry.get("id") == "bitemporal" for entry in staircases), (
        f"std-time-bound pack bundle must inherit default staircase reading, got channels={bundle_resp['body'].get('channels')}"
    )

    # 2. Gate serves GET /<pack>/<manifest>/readings/staircase?subject=<id> as rezono.staircase/1.
    assert reading_resp["status"] == 200, reading_resp
    body = reading_resp["body"]
    assert body["format"] == "rezono.staircase/1"
    assert body["pack"] == PACK_NAME
    assert body["manifest"] == "m-2"
    assert body["subject"] == "cov-a"
    assert body["valid_times"] == ["p1", "p2"]
    assert [entry["manifest"] for entry in body["knowledge_times"]] == ["m-1", "m-2"]

    published_hashes = {
        "m-1": _witness_hashes(st_dir, "m-1", "reader"),
        "m-2": _witness_hashes(st_dir, "m-2", "reader"),
    }
    cells = {(c["manifest"], c["valid_at"]): c for c in body["cells"]}
    assert set(cells) == {("m-1", "p1"), ("m-1", "p2"), ("m-2", "p1"), ("m-2", "p2")}

    # Epoch 1: open-world unknown before end was recorded (value is None, never a placeholder).
    for ref_id in ("p1", "p2"):
        cell = cells[("m-1", ref_id)]
        assert cell["state"] == "unknown", cell
        assert cell["value"] is None, cell
        assert cell["reason"] == "end_not_recorded", cell

    # Epoch 2: end=16 is recorded -> positive at p1 (12), negative at p2 (18).
    assert cells[("m-2", "p1")]["state"] == "known"
    assert cells[("m-2", "p1")]["value"] == "positive"
    assert cells[("m-2", "p1")]["reason"] == "end_beyond_horizon"
    assert cells[("m-2", "p2")]["state"] == "known"
    assert cells[("m-2", "p2")]["value"] == "negative"
    assert cells[("m-2", "p2")]["reason"] == "ended"

    # Every cell references a real published witness with its canonical <base>witness/<H> IRI.
    for (mid, _ref_id), cell in cells.items():
        witness = cell["witness"]
        digest = witness["sha256"]
        assert digest in published_hashes[mid], (mid, witness)
        assert witness["iri"] == f"{BASE_IRI}witness/{digest}", witness
        assert not witness["iri"].startswith("rezono:w/"), witness

    # 3. Role-scoped non-disclosure: role `other` cannot read `cov-a` and receives the same 404 as missing.
    unauth_resp, missing_resp = ask(
        st_dir,
        "other",
        f"/{PACK_NAME}/m-2/readings/staircase?subject=cov-a",
        f"/{PACK_NAME}/m-2/readings/staircase?subject=cov-missing",
    )
    assert unauth_resp["status"] == 404, unauth_resp
    assert missing_resp["status"] == 404, missing_resp
    assert unauth_resp["body"] == missing_resp["body"]
