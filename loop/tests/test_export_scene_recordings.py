"""Unit tests for exporting Scene 1 and Scene 4 TypedRecordings from disposable cluster evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil

import pytest

from loop.cluster.export_scene_recordings import (
    ClusterRecorderReader,
    DEFAULT_PACK_PATH,
    STD_LOOP_PACK,
    build_scene_1_recording,
    build_scene_4_recording,
    export_recordings,
    main as export_main,
)
from loop.executor import execute
from loop.recording_cli import main as replay_cli_main
from loop.recording_input import load_recording
from loop.replay import replay_report
from loop.typed_recording import TypedRecording
from rezono_canon import canonical_sha256
from rezono_compiler import modules

REPO = Path(__file__).resolve().parents[2]


def _make_boundary(
    *,
    run: str,
    cut: str,
    managed_namespaces: list[str],
    protected_endpoints: list[str],
    exposed_endpoints: list[str],
    observed_at: str,
    admitted_round: str,
) -> dict[str, object]:
    cert = canonical_sha256({"run": run, "cut": cut, "exposed": exposed_endpoints})
    body = {
        "run": run,
        "cut": cut,
        "kind": "live_readback",
        "inventory_complete": True,
        "managed_namespaces": sorted(managed_namespaces),
        "protected_endpoints": sorted(protected_endpoints),
        "exposed_endpoints": sorted(exposed_endpoints),
        "certificate": cert,
        "admitted_round": admitted_round,
        "observed_at": observed_at,
    }
    return {**body, "receipt": f"sha256:{canonical_sha256(body)}"}


def _sample_scene_1_boundaries(run: str = "safe-start-9001-1") -> list[dict[str, object]]:
    namespaces = [f"{run}-core", f"{run}-dmz", f"{run}-recovery", f"{run}-workload"]
    endpoints = ["core/idp", "dmz/entry-gw"]
    return [
        _make_boundary(
            run=run,
            cut="opening",
            managed_namespaces=[],
            protected_endpoints=[],
            exposed_endpoints=[],
            observed_at="2026-11-21T12:00:00.100000Z",
            admitted_round="",
        ),
        _make_boundary(
            run=run,
            cut="namespaces",
            managed_namespaces=namespaces,
            protected_endpoints=[],
            exposed_endpoints=[],
            observed_at="2026-11-21T12:00:04.250000Z",
            admitted_round=canonical_sha256({"round": "namespaces"}),
        ),
        _make_boundary(
            run=run,
            cut="protected",
            managed_namespaces=namespaces,
            protected_endpoints=endpoints,
            exposed_endpoints=[],
            observed_at="2026-11-21T12:00:09.500000Z",
            admitted_round=canonical_sha256({"round": "protected"}),
        ),
        _make_boundary(
            run=run,
            cut="ready",
            managed_namespaces=namespaces,
            protected_endpoints=endpoints,
            exposed_endpoints=endpoints,
            observed_at="2026-11-21T12:00:15.750000Z",
            admitted_round=canonical_sha256({"round": "ready"}),
        ),
    ]


def _make_mgmt_event(run_id: str, attempt: str, kind: str, observed_at: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run": run_id,
        "attempt": attempt,
        "feature": "backup",
        "kind": kind,
        "observed_at": observed_at,
        **fields,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return {**payload, "evidence": f"sha256:{digest}"}


def _sample_scene_4_events(run_id: str = "9001", attempt: str = "1") -> list[dict[str, object]]:
    run_key = f"{run_id}-{attempt}"
    trial_id = f"management-trial-{run_key}"
    backup_id = f"management-copy-{run_key}"
    fence = f"management-fence-{run_key}"
    payload_sha = hashlib.sha256(b"rezono management backup marker sample\n").hexdigest()

    captured = _make_mgmt_event(
        run_id,
        attempt,
        "backup-completed",
        "2026-11-21T12:01:00.100000Z",
        backup=backup_id,
        source_cluster="management",
        payload_sha256=payload_sha,
        trial=trial_id,
        store="rezono-mgmt-backup-store",
        object_key=f"marker-{run_key}.txt",
        size=39,
    )
    binding = _make_mgmt_event(
        run_id,
        attempt,
        "management-dataset-bound",
        "2026-11-21T12:01:01.200000Z",
        trial=trial_id,
        dataset="management-catalog",
        backup=backup_id,
        source_cluster="management",
        source_evidence=captured["evidence"],
        payload_sha256=payload_sha,
        backup_state="current",
        decision="daily",
    )
    hold = _make_mgmt_event(
        run_id,
        attempt,
        "management-fence-acquired",
        "2026-11-21T12:01:05.300000Z",
        trial=trial_id,
        cluster="management",
        fence=fence,
        replicas=0,
        deployment_generation=2,
        policy_uid="uid-fence-1",
        policy_resource_version="42",
        pods=[],
    )
    opening = _make_mgmt_event(
        run_id,
        attempt,
        "management-unreachable",
        "2026-11-21T12:01:06.400000Z",
        cluster="management",
        probe_result="unreachable",
        trial=trial_id,
        phase="opening",
        detail="dial tcp 10.96.0.10:8080: i/o timeout",
    )
    readback = _make_mgmt_event(
        run_id,
        attempt,
        "recovered-read",
        "2026-11-21T12:01:10.500000Z",
        backup=backup_id,
        dataset="management-catalog",
        cluster="recovery",
        trial=trial_id,
        source_evidence=captured["evidence"],
        payload_sha256=payload_sha,
        isolated=True,
        active_authority=False,
    )
    closing = _make_mgmt_event(
        run_id,
        attempt,
        "management-unreachable",
        "2026-11-21T12:01:12.600000Z",
        cluster="management",
        probe_result="unreachable",
        trial=trial_id,
        phase="closing",
        detail="dial tcp 10.96.0.10:8080: i/o timeout",
    )
    coverage = _make_mgmt_event(
        run_id,
        attempt,
        "management-fence-coverage",
        "2026-11-21T12:01:13.700000Z",
        trial=trial_id,
        cluster="management",
        fence=fence,
        fence_evidence=hold["evidence"],
        complete=True,
        lost=0,
        watched_pod_events=0,
        start=hold["observed_at"],
        end=closing["observed_at"],
        opening_probe=opening["evidence"],
        closing_probe=closing["evidence"],
        readback_evidence=readback["evidence"],
    )
    return [captured, binding, hold, opening, readback, closing, coverage]


def _copy_std_loop_packs(target_dir: Path) -> str:
    for name in ("std-order", "std-loop"):
        shutil.copytree(REPO / "packs" / name, target_dir / name)
    return "std-loop"


def test_scene_1_export_replays_and_round_trips_through_executor(tmp_path, capsys):
    boundaries = _sample_scene_1_boundaries()
    recording, manifest = build_scene_1_recording(boundaries)

    assert recording["pack"]["path"] == DEFAULT_PACK_PATH
    assert recording["pack"]["sha256"] == modules.pack_hash(STD_LOOP_PACK)
    assert (REPO / "examples/platform/recordings/scene-1-build-from-empty" / DEFAULT_PACK_PATH).resolve() == STD_LOOP_PACK.resolve()

    assert manifest["scene"] == 1
    assert manifest["origin"] == "real"
    assert manifest["captured_on"] == "2026-11-21"
    assert manifest["capture_evidence"].startswith("disposable-cluster:safe-start-9001-1:ready:sha256:")
    assert manifest["expected_plans"] == [["prepare-namespaces"], ["protect-endpoints"], ["expose-endpoints"]]
    assert manifest["expected_outcome"] == "success"

    # Load from disk via load_recording and replay via replay_report + recording_cli.
    rel_pack = _copy_std_loop_packs(tmp_path)
    local_recording, local_manifest = build_scene_1_recording(boundaries, pack_path=rel_pack)
    rec_path = tmp_path / "scene-1-recording.json"
    rec_path.write_text(json.dumps(local_recording, indent=2) + "\n", encoding="utf-8")

    loaded = load_recording(rec_path)
    assert isinstance(loaded, TypedRecording)
    plans, outcome, fixed_point = replay_report(loaded.run, loaded.limit, loaded.snapshots(), report_limit=True)
    assert plans == local_manifest["expected_plans"]
    assert outcome == local_manifest["expected_outcome"] == "success"
    assert fixed_point == []

    status = replay_cli_main([str(rec_path)])
    cli_report = json.loads(capsys.readouterr().out)
    assert status == 0
    assert cli_report == {"plans": plans, "outcome": "success", "rounds": 3}

    # Round-trip through loop/executor.py with the recorded readback sweeps.
    base_input = {**local_recording, "sweeps": []}
    recorded_sweeps = local_recording["sweeps"]
    applied: list[tuple[str, int, str]] = []

    def apply_step(run: str, round_number: int, step: str) -> str:
        applied.append((run, round_number, step))
        return "applied"

    def read_sweep_fn(run: str, round_number: int) -> dict[str, object]:
        return recorded_sweeps[round_number - 1]

    report, executed_recording = execute(tmp_path, base_input, apply=apply_step, read=read_sweep_fn)
    assert applied == [
        ("safe-start-9001-1", 1, "prepare-namespaces"),
        ("safe-start-9001-1", 2, "protect-endpoints"),
        ("safe-start-9001-1", 3, "expose-endpoints"),
    ]
    assert report == {"plans": plans, "outcome": "success", "rounds": 3, "findings": []}
    assert executed_recording == local_recording

    # Without readback (unknown-only sweeps), readiness is never proven and execution fails at round limit.
    def read_unknown_only(run: str, round_number: int) -> dict[str, object]:
        return {
            "id": f"silent-{round_number}",
            "run": run,
            "event_time": round_number * 1_000_000,
            "complete": True,
            "observations": [],
        }

    silent_report, _ = execute(tmp_path, base_input, apply=lambda *_: "applied", read=read_unknown_only)
    assert silent_report["outcome"] == "failure"
    assert silent_report["plans"] == [["prepare-namespaces"]] * base_input["limit"]
    assert silent_report["rounds"] == base_input["limit"]

    # Stripping known readback from the final sweep leaves readiness unproven (pending, not success).
    no_ready = deepcopy(local_recording)
    no_ready["sweeps"][-1]["observations"][0]["observation"]["value"] = {"state": "unknown", "reason": "no_value"}
    no_ready_path = tmp_path / "scene-1-no-ready.json"
    no_ready_path.write_text(json.dumps(no_ready, indent=2) + "\n", encoding="utf-8")
    loaded_unproven = load_recording(no_ready_path)
    assert isinstance(loaded_unproven, TypedRecording)
    unproven_plans, unproven_outcome, _ = replay_report(
        loaded_unproven.run, loaded_unproven.limit, loaded_unproven.snapshots(), report_limit=True
    )
    assert unproven_plans == [["prepare-namespaces"], ["protect-endpoints"], ["expose-endpoints"]]
    assert unproven_outcome == "pending"


def test_scene_4_export_replays_and_round_trips_through_executor(tmp_path, capsys):
    events = _sample_scene_4_events()
    recording, manifest = build_scene_4_recording(events)

    assert recording["pack"]["path"] == DEFAULT_PACK_PATH
    assert recording["pack"]["sha256"] == modules.pack_hash(STD_LOOP_PACK)
    assert (REPO / "examples/platform/recordings/scene-4-failure-or-drift" / DEFAULT_PACK_PATH).resolve() == STD_LOOP_PACK.resolve()

    assert manifest["scene"] == 4
    assert manifest["origin"] == "real"
    assert manifest["captured_on"] == "2026-11-21"
    assert manifest["capture_evidence"].startswith("disposable-cluster:record-backup-9001-1:coverage:sha256:")
    assert manifest["expected_plans"] == [["fence-management"], ["restore-copy"], ["verify-fence-coverage"]]
    assert manifest["expected_outcome"] == "success"

    rel_pack = _copy_std_loop_packs(tmp_path)
    local_recording, local_manifest = build_scene_4_recording(events, pack_path=rel_pack)
    rec_path = tmp_path / "scene-4-recording.json"
    rec_path.write_text(json.dumps(local_recording, indent=2) + "\n", encoding="utf-8")

    loaded = load_recording(rec_path)
    assert isinstance(loaded, TypedRecording)
    plans, outcome, fixed_point = replay_report(loaded.run, loaded.limit, loaded.snapshots(), report_limit=True)
    assert plans == local_manifest["expected_plans"]
    assert outcome == local_manifest["expected_outcome"] == "success"
    assert fixed_point == []

    status = replay_cli_main([str(rec_path)])
    cli_report = json.loads(capsys.readouterr().out)
    assert status == 0
    assert cli_report == {"plans": plans, "outcome": "success", "rounds": 3}

    # Round-trip through loop/executor.py with the recorded readback sweeps.
    base_input = {**local_recording, "sweeps": []}
    recorded_sweeps = local_recording["sweeps"]
    applied: list[tuple[str, int, str]] = []

    report, executed_recording = execute(
        tmp_path,
        base_input,
        apply=lambda run, rnd, step: applied.append((run, rnd, step)) or "applied",
        read=lambda run, rnd: recorded_sweeps[rnd - 1],
    )
    assert applied == [
        ("offline-restore-9001-1", 1, "fence-management"),
        ("offline-restore-9001-1", 2, "restore-copy"),
        ("offline-restore-9001-1", 3, "verify-fence-coverage"),
    ]
    assert report == {"plans": plans, "outcome": "success", "rounds": 3, "findings": []}
    assert executed_recording == local_recording

    # Without readback, fence-management never completes and hits the round limit.
    silent_report, _ = execute(
        tmp_path,
        base_input,
        apply=lambda *_: "applied",
        read=lambda run, rnd: {
            "id": f"silent-{rnd}",
            "run": run,
            "event_time": (rnd + 10) * 1_000_000,
            "complete": True,
            "observations": [],
        },
    )
    assert silent_report["outcome"] == "failure"
    assert silent_report["plans"] == [["fence-management"]] * base_input["limit"]

    # Drifted readback (management still reachable) produces a drift finding and stops immediately.
    drifted_sweep = deepcopy(recorded_sweeps[0])
    drifted_sweep["observations"][1]["observation"]["value"] = {"state": "known", "value": "reachable"}
    drift_report, _ = execute(
        tmp_path,
        base_input,
        apply=lambda *_: "applied",
        read=lambda run, rnd: drifted_sweep,
    )
    assert drift_report["outcome"] == "failure"
    assert drift_report["rounds"] == 1
    assert len(drift_report["findings"]) == 1
    assert drift_report["findings"][0]["token"] == "management/availability"


def test_scene_1_and_scene_4_builders_reject_tampered_or_invalid_evidence():
    tampered_s1 = _sample_scene_1_boundaries()
    tampered_s1[-1]["exposed_endpoints"] = ["dmz/entry-gw"]
    with pytest.raises(ValueError, match="receipt mismatch"):
        build_scene_1_recording(tampered_s1)

    tampered_s4 = _sample_scene_4_events()
    tampered_s4[-1]["lost"] = 1
    with pytest.raises(ValueError, match="evidence mismatch"):
        build_scene_4_recording(tampered_s4)

    # Valid digest but broken outage interval (lost=1) must still be refused.
    broken_s4 = _sample_scene_4_events()
    broken_cov = {k: v for k, v in broken_s4[-1].items() if k != "evidence"}
    broken_cov["lost"] = 1
    broken_cov["evidence"] = "sha256:" + hashlib.sha256(
        json.dumps(broken_cov, sort_keys=True).encode("utf-8")
    ).hexdigest()
    broken_s4[-1] = broken_cov
    with pytest.raises(ValueError, match="zero lost intervals"):
        build_scene_4_recording(broken_s4)


def test_cluster_reader_and_cli_export_both_scenes_with_pure_lf(tmp_path):
    kubeconfig = tmp_path / "fixture.kubeconfig"
    kubeconfig.write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")

    boundaries = _sample_scene_1_boundaries("safe-start-9001-1")
    backup_events = _sample_scene_4_events("9001", "1")

    boundary_jobs = [
        {
            "metadata": {
                "name": f"safe-start-9001-1-b{i}",
                "uid": f"b-uid-{i}",
                "labels": {
                    "rezono.org/safe-start-run": "safe-start-9001-1",
                    "rezono.org/role": "boundary-recorder",
                },
            },
            "status": {"succeeded": 1},
        }
        for i in range(len(boundaries))
    ]
    backup_job = {
        "metadata": {
            "name": "record-backup-9001-1",
            "uid": "backup-uid-1",
            "labels": {
                "rezono.org/management-feature": "backup",
                "rezono.org/recorder-run": "9001-1",
            },
        },
        "status": {"succeeded": 1},
    }

    def fake_runner(args, *, timeout=30):
        cmd = list(args)
        if cmd[-2:] == ["config", "current-context"]:
            return "kind-rezono-fixture\n"
        if "jsonpath={.clusters[0].cluster.server}" in cmd:
            return "https://127.0.0.1:6443\n"
        if "jobs" in cmd and any("boundary-recorder" in arg for arg in cmd):
            return json.dumps({"items": boundary_jobs})
        if "jobs" in cmd and any("management-feature=backup" in arg for arg in cmd):
            return json.dumps({"items": [backup_job]})
        if "pods" in cmd:
            label = cmd[cmd.index("-l") + 1]
            job_name = label.removeprefix("job-name=")
            if job_name == "record-backup-9001-1":
                uid = "backup-uid-1"
            else:
                index = int(job_name.rsplit("-b", 1)[1])
                uid = f"b-uid-{index}"
            return json.dumps({
                "items": [{
                    "metadata": {
                        "name": f"{job_name}-pod",
                        "ownerReferences": [{"uid": uid, "controller": True}],
                    },
                    "status": {"phase": "Succeeded"},
                }]
            })
        if "logs" in cmd:
            pod_name = cmd[cmd.index("logs") + 1]
            if pod_name == "record-backup-9001-1-pod":
                return "".join(json.dumps(row, sort_keys=True) + "\n" for row in backup_events)
            index = int(pod_name.removesuffix("-pod").rsplit("-b", 1)[1])
            return json.dumps(boundaries[index], sort_keys=True) + "\n"
        raise AssertionError(f"Unexpected kubectl invocation: {cmd}")

    reader = ClusterRecorderReader(
        kubeconfig,
        env={"GITHUB_RUN_ID": "9001", "GITHUB_RUN_ATTEMPT": "1"},
        runner=fake_runner,
    )
    out_dir = tmp_path / "exported"
    exported = export_recordings(out_dir, reader=reader, require_all=True)
    assert set(exported) == {1, 4}

    for scene, (rec_path, man_path) in exported.items():
        for file_path in (rec_path, man_path):
            raw = file_path.read_bytes()
            assert b"\r" not in raw, f"{file_path.name} must use pure LF"
            assert raw.endswith(b"\n")
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
        assert manifest["scene"] == scene
        assert manifest["origin"] == "real"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", manifest["captured_on"])
        assert manifest["capture_evidence"].strip()
        assert manifest["expected_outcome"] == "success"

    # Partial export succeeds when only one scene exists and require_all=False, but fails with require_all=True.
    def backup_only_runner(args, *, timeout=30):
        if "jobs" in args and any("boundary-recorder" in arg for arg in args):
            return json.dumps({"items": []})
        return fake_runner(args, timeout=timeout)

    partial_reader = ClusterRecorderReader(
        kubeconfig,
        env={"GITHUB_RUN_ID": "9001", "GITHUB_RUN_ATTEMPT": "1"},
        runner=backup_only_runner,
    )
    partial_dir = tmp_path / "partial"
    partial_exported = export_recordings(partial_dir, reader=partial_reader, require_all=False)
    assert set(partial_exported) == {4}
    with pytest.raises(RuntimeError, match="Scene 1"):
        export_recordings(tmp_path / "strict", reader=partial_reader, require_all=True)


def test_cluster_reader_rejects_non_loopback_server_and_wrong_context(tmp_path):
    kubeconfig = tmp_path / "bad.kubeconfig"
    kubeconfig.write_text("apiVersion: v1\nkind: Config\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="current-context"):
        ClusterRecorderReader(kubeconfig, runner=lambda *_, **__: "other-context\n")

    def remote_runner(args, *, timeout=30):
        if list(args)[-2:] == ["config", "current-context"]:
            return "kind-rezono-fixture\n"
        return "https://203.0.113.10:6443\n"

    with pytest.raises(RuntimeError, match="runner-local"):
        ClusterRecorderReader(kubeconfig, runner=remote_runner)


def test_export_cli_requires_kubeconfig_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("REZONO_CLUSTER_KUBECONFIG", raising=False)
    monkeypatch.delenv("KUBECONFIG", raising=False)
    with pytest.raises(SystemExit) as exc:
        export_main(["--out-dir", str(tmp_path / "out")])
    assert exc.value.code == 2
