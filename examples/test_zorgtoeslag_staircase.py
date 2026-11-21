"""Publishing `examples/zorgtoeslag-slice` as a pack and serving its bitemporal staircase reading
via `edge/gate/src/local.ts` (decisions/bitemporal-staircase-reading.md,
decisions/language-healthcare-allowance-slice.md, decisions/healthcare-allowance-three-sources.md).

Supports both the single-source first-slice keys (`bob`, `gus`) and the three-source keys
(`p-bob`, `p-gus`), comparing every served cell against the independent stdlib-only oracle
`examples/zorgtoeslag-slice/reference.py`.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

ROOT = Path(__file__).resolve().parents[1]
SLICE = ROOT / "examples" / "zorgtoeslag-slice"
PACK = SLICE / "pack.yaml"
README = SLICE / "README.md"
ORACLE = SLICE / "reference.py"

sys.path.insert(0, str(ROOT / "tests" / "slip"))
from slip_support import ask  # noqa: E402

ROLES = {"checker": "complete", "reader": "may_read"}


def _load_oracle():
    assert ORACLE.is_file(), f"{ORACLE.relative_to(ROOT).as_posix()} does not exist"
    spec = importlib.util.spec_from_file_location("zorgtoeslag_staircase_reference", ORACLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _facts_source() -> tuple[Path, bool]:
    facts_dir = SLICE / "facts"
    if facts_dir.is_dir():
        return facts_dir, True
    return SLICE / "facts.rezono", False


def _subject_id(short: str, three_sources: bool) -> str:
    return f"p-{short}" if three_sources else short


def _expected_from_oracle(oracle, facts_src: Path, subject: str, as_of_iso: str, known_iso: str):
    got = oracle.allowance(
        facts_src,
        subject,
        datetime.date.fromisoformat(as_of_iso),
        datetime.date.fromisoformat(known_iso),
    )
    if isinstance(got, int):
        return ("known", str(got), "")
    return (str(got[0]), None, str(got[1]))


def _role_witness_hashes(store_dir: Path, pack_name: str, manifest_id: str, role: str) -> set[str]:
    from rezono_canon import canonical_sha256

    manifest = json.loads((store_dir / pack_name / "manifests" / f"{manifest_id}.json").read_text(encoding="utf-8"))
    ref = next(entry for entry in manifest.get("witnesses") or [] if entry["role"] == role)
    key = ref["uri"].split("://", 1)[1].split("/", 1)[1]
    payload = json.loads((store_dir / key).read_text(encoding="utf-8"))
    all_witnesses = list(payload.get("witnesses") or []) + list(payload.get("calc_witnesses") or [])
    return {canonical_sha256(w) for w in all_witnesses}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/bitemporal-staircase-reading.md: Give examples/zorgtoeslag-slice its "
        "pack.yaml, README.md, channels.yaml, labels/messages, and reader role, support optional "
        "as_of/known ISO dates in rezono_publisher.batch.epoch, and publish examples/zorgtoeslag-slice "
        "cleanly via rezono_publisher with green proofs and gate-served allowance rows matching "
        "examples/zorgtoeslag-slice/reference.py."
    ),
)
def test_zorgtoeslag_slice_compiles_and_publishes_via_publisher(tmp_path: Path):
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
    assert README.is_file() and README.read_text(encoding="utf-8").strip(), (
        f"{README.relative_to(ROOT).as_posix()} must exist and be non-empty"
    )
    meta = yaml.safe_load(PACK.read_text(encoding="utf-8"))
    assert meta.get("name") == "zorgtoeslag-slice", meta

    from rezono_compiler import emit, pack
    from rezono_publisher import batch, publish, store

    try:
        model = pack.read(SLICE)
        compiled = emit.compile_pack(model)
    except pack.CompileError as err:
        raise AssertionError(f"examples/zorgtoeslag-slice failed to compile: {err}") from err

    assert "bundle/schema-bundle.json" in compiled
    assert "ir/calc.json" in compiled

    st_dir = tmp_path / "store"
    st = store.FileStore(st_dir)
    ep = batch.epoch(
        SLICE,
        epoch=1,
        knowledge_time="2026-02-10T00:00:00Z",
        sources=[("rules", "test")],
        as_of="2026-02-01",
        known="2026-02-10",
    )
    manifest = publish.publish(ep, st, ROLES)
    assert manifest["id"] == "m-1"
    proof_checks = [c for c in manifest.get("checks") or [] if c.get("name") == "rezono:proofs"]
    assert proof_checks == [{"name": "rezono:proofs", "status": "green", "violations": 0}], manifest.get("checks")

    # Verify published allowance row for bob / p-bob against the independent oracle via edge/gate/src/local.ts.
    oracle = _load_oracle()
    facts_src, three_sources = _facts_source()
    bob_id = _subject_id("bob", three_sources)
    want_state, want_value, want_reason = _expected_from_oracle(oracle, facts_src, bob_id, "2026-02-01", "2026-02-10")
    assert (want_state, want_value, want_reason) == ("known", "10500", "")

    head_resp, bundle_resp = ask(st_dir, "reader", "/zorgtoeslag-slice/head", "/zorgtoeslag-slice/bundle")
    assert head_resp["status"] == 200 and head_resp["body"]["witness_check"] == "green", head_resp
    assert bundle_resp["status"] == 200, bundle_resp

    calc_outputs = bundle_resp["body"].get("calc") or []
    allowance_out = next((entry for entry in calc_outputs if entry.get("rule") == "allowance"), None)
    assert allowance_out is not None, f"bundle calc outputs missing allowance: {calc_outputs}"
    allowance_rel = allowance_out["view"]

    [rows_resp] = ask(st_dir, "reader", f"/zorgtoeslag-slice/m-1/rows/{allowance_rel}")
    assert rows_resp["status"] == 200, rows_resp
    bob_rows = [row["key"] for row in rows_resp["body"]["rows"] if row["key"][0] == bob_id]
    assert bob_rows == [[bob_id, want_value, want_state, want_reason]], bob_rows


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/bitemporal-staircase-reading.md: Publish the bitemporal history of "
        "examples/zorgtoeslag-slice via rezono_publisher.history.publish_bitemporal_history and "
        "serve GET /zorgtoeslag-slice/<manifest>/readings/staircase through edge/gate/src/local.ts "
        "matching examples/zorgtoeslag-slice/reference.py for bob/p-bob (unknown before 2025-12-01, "
        "10500 after) and gus/p-gus (13500 before 2026-04-15, retroactive 8500 after) with verified "
        "canonical <base>witness/<H> IRIs. Waits for "
        "examples/test_zorgtoeslag_staircase.py--test_zorgtoeslag_slice_compiles_and_publishes_via_publisher "
        "and tests/slip/test_bitemporal_staircase_reading.py--test_std_time_bound_pack_serves_bitemporal_staircase_reading_via_gate."
    ),
)
def test_zorgtoeslag_slice_bitemporal_staircase_served_via_gate(tmp_path: Path):
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"

    try:
        from rezono_publisher import history
    except ImportError as err:
        raise AssertionError(f"rezono_publisher.history is not implemented yet: {err}") from err
    assert callable(getattr(history, "publish_bitemporal_history", None)), (
        "rezono_publisher.history must expose publish_bitemporal_history"
    )

    valid_dates = ["2026-01-01", "2026-02-01", "2026-04-01"]
    knowledge_dates = ["2025-11-15", "2026-02-10", "2026-05-01"]

    st_dir = tmp_path / "store"
    history.publish_bitemporal_history(
        SLICE,
        st_dir,
        ROLES,
        valid_dates=valid_dates,
        knowledge_dates=knowledge_dates,
    )

    oracle = _load_oracle()
    facts_src, three_sources = _facts_source()
    bob_id = _subject_id("bob", three_sources)
    gus_id = _subject_id("gus", three_sources)

    [head_resp, bundle_resp] = ask(st_dir, "reader", "/zorgtoeslag-slice/head", "/zorgtoeslag-slice/bundle")
    assert head_resp["status"] == 200 and head_resp["body"]["witness_check"] == "green", head_resp
    assert bundle_resp["status"] == 200, bundle_resp
    latest_manifest = head_resp["body"]["id"]

    # Determine the canonical schema base of the published pack (from bundle/pack iri or schema base).
    from rezono_publication import publication as rd_pub

    schema_doc, _ = rd_pub.schema_document(bundle_resp["body"])
    base_iri = schema_doc["base"]

    bob_resp, gus_resp, missing_resp = ask(
        st_dir,
        "reader",
        f"/zorgtoeslag-slice/{latest_manifest}/readings/staircase?subject={bob_id}",
        f"/zorgtoeslag-slice/{latest_manifest}/readings/staircase?subject={gus_id}",
        f"/zorgtoeslag-slice/{latest_manifest}/readings/staircase?subject=no-such-subject",
    )
    assert bob_resp["status"] == 200, bob_resp
    assert gus_resp["status"] == 200, gus_resp
    assert missing_resp["status"] == 404, missing_resp

    witness_cache: dict[str, set[str]] = {}
    for subject_id, resp in ((bob_id, bob_resp), (gus_id, gus_resp)):
        body = resp["body"]
        assert body["format"] == "rezono.staircase/1"
        assert body["pack"] == "zorgtoeslag-slice"
        assert body["manifest"] == latest_manifest
        assert body["subject"] == subject_id
        assert body["valid_times"] == valid_dates

        by_coords = {(c["valid_at"], c["known_at"][:10]): c for c in body["cells"]}
        for valid_iso in valid_dates:
            for known_iso in knowledge_dates:
                assert (valid_iso, known_iso) in by_coords, (subject_id, valid_iso, known_iso, sorted(by_coords))
                cell = by_coords[(valid_iso, known_iso)]
                want_state, want_value, want_reason = _expected_from_oracle(
                    oracle, facts_src, subject_id, valid_iso, known_iso
                )
                assert (cell["state"], cell["value"], cell["reason"]) == (want_state, want_value, want_reason), (
                    subject_id, valid_iso, known_iso, cell
                )
                mid = cell["manifest"]
                if mid not in witness_cache:
                    witness_cache[mid] = _role_witness_hashes(st_dir, "zorgtoeslag-slice", mid, "reader")
                digest = cell["witness"]["sha256"]
                assert digest in witness_cache[mid], (subject_id, mid, cell["witness"])
                assert cell["witness"]["iri"] == f"{base_iri}witness/{digest}", cell["witness"]
                assert not cell["witness"]["iri"].startswith("rezono:w/"), cell["witness"]

    # Spot-check the two defining Cartouche M1 staircase transitions explicitly:
    bob_cells = {(c["valid_at"], c["known_at"][:10]): c for c in bob_resp["body"]["cells"]}
    assert bob_cells[("2026-02-01", "2025-11-15")]["state"] == "unknown"
    assert bob_cells[("2026-02-01", "2025-11-15")]["value"] is None
    assert bob_cells[("2026-02-01", "2025-11-15")]["reason"] == "no_version_applies"
    assert bob_cells[("2026-02-01", "2026-02-10")]["state"] == "known"
    assert bob_cells[("2026-02-01", "2026-02-10")]["value"] == "10500"

    gus_cells = {(c["valid_at"], c["known_at"][:10]): c for c in gus_resp["body"]["cells"]}
    assert gus_cells[("2026-01-01", "2026-02-10")]["value"] == "13500"
    assert gus_cells[("2026-01-01", "2026-05-01")]["value"] == "8500"
    assert gus_cells[("2026-04-01", "2026-05-01")]["value"] == "8500"
