"""Export offline-replayable std-loop TypedRecordings from the disposable Kind cluster."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date
import hashlib
from ipaddress import ip_address
import json
from math import lcm
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
STD_LOOP_PACK = ROOT / "packs" / "std-loop"
DEFAULT_PACK_PATH = "../../../../packs/std-loop"
CONTEXT = "kind-rezono-fixture"
PROBE_NAMESPACE = "rezono-probes"
RUN_LABEL = "rezono.org/safe-start-run"
ROLE_LABEL = "rezono.org/role"
BOUNDARY_ROLE = "boundary-recorder"
MANAGEMENT_FEATURE_LABEL = "rezono.org/management-feature"
RECORDER_RUN_LABEL = "rezono.org/recorder-run"
SCENE_1_CUTS = ("opening", "namespaces", "protected", "ready")
FORBIDDEN_OUTAGE_KINDS = frozenset({
    "management-reachable",
    "management-fence-broken",
    "management-authority-enabled",
})
DEFAULT_LIMIT = 6
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SCENE_1_READER_PORT: dict[str, Any] = {
    "name": "cluster-readback",
    "version": "1.0.0",
    "kind": "in",
    "runs_on": "source",
    "writes": "observation",
    "row_source": "source",
    "runtime": "in_process",
    "consumes": ["cluster_boundary"],
    "produces": ["loop_observation"],
    "freshness": {"cadence": "on_request"},
    "mapping_owner": "platform-loop",
    "losses": [],
    "secrets": [],
}

SCENE_1_EFFECT_PORT: dict[str, Any] = {
    "name": "cluster-apply",
    "version": "1.0.0",
    "kind": "effect",
    "runs_on": "approved_plan",
    "writes": "world",
    "row_source": "journal",
    "runtime": "in_process",
    "effect": {
        "plan": "startup-plan",
        "apply": "startup-apply",
        "status": "startup-status",
    },
    "consumes": ["loop_step"],
    "produces": ["cluster_boundary"],
    "freshness": {"cadence": "on_request"},
    "mapping_owner": "platform-loop",
    "losses": [],
    "secrets": [],
}

SCENE_4_READER_PORT: dict[str, Any] = {
    "name": "backup-readback",
    "version": "1.0.0",
    "kind": "in",
    "runs_on": "source",
    "writes": "observation",
    "row_source": "source",
    "runtime": "in_process",
    "consumes": ["backup_event"],
    "produces": ["loop_observation"],
    "freshness": {"cadence": "on_request"},
    "mapping_owner": "platform-loop",
    "losses": [],
    "secrets": [],
}

SCENE_4_EFFECT_PORT: dict[str, Any] = {
    "name": "recovery-apply",
    "version": "1.0.0",
    "kind": "effect",
    "runs_on": "approved_plan",
    "writes": "world",
    "row_source": "journal",
    "runtime": "in_process",
    "effect": {
        "plan": "restore-plan",
        "apply": "restore-apply",
        "status": "restore-status",
    },
    "consumes": ["loop_step"],
    "produces": ["backup_event"],
    "freshness": {"cadence": "on_request"},
    "mapping_owner": "platform-loop",
    "losses": [],
    "secrets": [],
}


def _std_loop_hash(pack_dir: Path = STD_LOOP_PACK) -> str:
    from rezono_compiler import modules

    return modules.pack_hash(pack_dir)


def _iso_day(timestamp: str, label: str) -> str:
    if not isinstance(timestamp, str) or len(timestamp) < 10:
        raise ValueError(f"{label} must be an ISO-8601 timestamp, got {timestamp!r}")
    day = timestamp[:10]
    if not ISO_DAY.fullmatch(day):
        raise ValueError(f"{label} date prefix must be YYYY-MM-DD, got {day!r}")
    date.fromisoformat(day)
    return day


def _clock_and_ticks(timestamps: Sequence[str]) -> tuple[dict[str, Any], Callable[[str], int]]:
    from loop.typed_recording import instant

    if not timestamps:
        raise ValueError("at least one observation timestamp is required")
    parsed = [(ts, instant(ts)) for ts in timestamps]
    origin_str, origin_time = min(parsed, key=lambda item: item[1])
    denominators = [(at - origin_time).denominator for _, at in parsed]
    ticks_per_second = lcm(1_000_000, *denominators)

    def to_tick(ts: str) -> int:
        delta = (instant(ts) - origin_time) * ticks_per_second
        if delta.denominator != 1:
            raise ValueError(f"timestamp {ts!r} did not align to integer clock ticks")
        return int(delta)

    return {"origin": origin_str, "ticks_per_second": ticks_per_second}, to_tick


def _known_observation(
    *,
    run: str,
    sweep: str,
    port: str,
    obs_id: str,
    subject: str,
    attribute: str,
    token: str,
    value: str,
    event_time: str,
    position: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "run": run,
        "sweep": sweep,
        "port": port,
        "reason": reason,
        "observation": {
            "id": obs_id,
            "subject": subject,
            "attribute": attribute,
            "value": {"state": "known", "value": value},
            "event_time": event_time,
            "source": {"kind": "tool", "name": port, "position": position},
            "expectation": {"relation": "loop_expectation__value", "key": json.dumps([token])},
        },
    }


def _unknown_observation(
    *,
    run: str,
    sweep: str,
    port: str,
    obs_id: str,
    subject: str,
    attribute: str,
    token: str,
    event_time: str,
    position: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "run": run,
        "sweep": sweep,
        "port": port,
        "reason": reason,
        "observation": {
            "id": obs_id,
            "subject": subject,
            "attribute": attribute,
            "value": {"state": "unknown", "reason": "no_value"},
            "event_time": event_time,
            "source": {"kind": "tool", "name": port, "position": position},
            "expectation": {"relation": "loop_expectation__value", "key": json.dumps([token])},
        },
    }


def _dated_sweep(
    *,
    sweep_id: str,
    run: str,
    event_time: int,
    observations: list[dict[str, Any]],
    complete: bool = True,
) -> dict[str, Any]:
    return {
        "id": sweep_id,
        "run": run,
        "event_time": event_time,
        "complete": complete,
        "observations": observations,
    }


def _verify_boundary_receipt(boundary: Mapping[str, Any]) -> None:
    from rezono_canon import canonical_sha256

    receipt = boundary.get("receipt")
    if not isinstance(receipt, str) or not receipt.startswith("sha256:") or not HEX_64.fullmatch(receipt[7:]):
        raise ValueError(f"boundary {boundary.get('cut')!r} has invalid receipt {receipt!r}")
    body = {k: v for k, v in boundary.items() if k != "receipt"}
    expected = f"sha256:{canonical_sha256(body)}"
    if receipt != expected:
        raise ValueError(f"boundary {boundary.get('cut')!r} receipt mismatch: {receipt} != {expected}")


def _verify_management_event_digest(event: Mapping[str, Any]) -> None:
    evidence = event.get("evidence")
    if not isinstance(evidence, str) or not evidence.startswith("sha256:") or not HEX_64.fullmatch(evidence[7:]):
        raise ValueError(f"management event {event.get('kind')!r} has invalid evidence {evidence!r}")
    payload = {k: v for k, v in event.items() if k != "evidence"}
    expected = "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    if evidence != expected:
        raise ValueError(f"management event {event.get('kind')!r} evidence mismatch: {evidence} != {expected}")


def verify_recording_offline(
    data: Mapping[str, Any],
    *,
    pack_dir: Path = STD_LOOP_PACK,
) -> tuple[list[list[str]], str, list[tuple[str, ...]]]:
    """Validate and replay a TypedRecording dict completely offline against std-loop."""
    from loop.replay import replay_report
    from loop.typed_recording import TypedRecording, typed_recording

    plain = json.loads(json.dumps(data, allow_nan=False))
    if plain != data:
        raise ValueError("recording must serialize cleanly as plain JSON")
    pack_pin = plain.get("pack")
    if not isinstance(pack_pin, dict) or Path(str(pack_pin.get("path", ""))).anchor:
        raise ValueError("recording pack.path must be a relative path")
    expected_hash = _std_loop_hash(pack_dir)
    if pack_pin.get("sha256") != expected_hash:
        raise ValueError(f"recording pack.sha256 {pack_pin.get('sha256')!r} != {expected_hash!r}")

    verify_copy = {**plain, "pack": {"path": pack_dir.name, "sha256": expected_hash}}
    loaded = typed_recording(pack_dir.parent, verify_copy)
    if not isinstance(loaded, TypedRecording):
        raise ValueError("expected a TypedRecording from typed_recording()")
    return replay_report(loaded.run, loaded.limit, loaded.snapshots(), report_limit=True)


def build_scene_1_recording(
    boundaries: Sequence[Mapping[str, Any]],
    *,
    pack_path: str = DEFAULT_PACK_PATH,
    pack_sha256: str | None = None,
    limit: int = DEFAULT_LIMIT,
    pack_dir: Path = STD_LOOP_PACK,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert Scene 1 live startup boundaries into an offline-replayable TypedRecording and manifest."""
    if len(boundaries) != len(SCENE_1_CUTS):
        raise ValueError(f"Scene 1 requires {len(SCENE_1_CUTS)} boundaries ({SCENE_1_CUTS}), got {len(boundaries)}")

    by_cut: dict[str, Mapping[str, Any]] = {}
    for entry in boundaries:
        cut = entry.get("cut")
        if cut not in SCENE_1_CUTS or cut in by_cut:
            raise ValueError(f"unexpected or duplicate Scene 1 boundary cut: {cut!r}")
        if entry.get("kind") != "live_readback" or entry.get("inventory_complete") is not True:
            raise ValueError(f"Scene 1 boundary {cut!r} must be a complete live_readback")
        if not isinstance(entry.get("certificate"), str) or not entry["certificate"].strip():
            raise ValueError(f"Scene 1 boundary {cut!r} is missing its transition certificate")
        _verify_boundary_receipt(entry)
        by_cut[cut] = entry

    b_open = by_cut["opening"]
    b_ns = by_cut["namespaces"]
    b_prot = by_cut["protected"]
    b_ready = by_cut["ready"]

    runs = {b["run"] for b in (b_open, b_ns, b_prot, b_ready)}
    if len(runs) != 1 or not next(iter(runs)):
        raise ValueError(f"Scene 1 boundaries must share one non-empty run ID, got {sorted(runs)!r}")
    run = str(next(iter(runs)))

    if b_open.get("managed_namespaces") != [] or b_open.get("protected_endpoints") != [] or b_open.get("exposed_endpoints") != []:
        raise ValueError("Scene 1 opening boundary must start empty")

    namespaces = sorted(str(item) for item in b_ns.get("managed_namespaces", ()))
    protected = sorted(str(item) for item in b_prot.get("protected_endpoints", ()))
    exposed = sorted(str(item) for item in b_ready.get("exposed_endpoints", ()))
    if not namespaces:
        raise ValueError("Scene 1 namespaces boundary must record non-empty managed_namespaces")
    if b_ns.get("protected_endpoints") != [] or b_ns.get("exposed_endpoints") != []:
        raise ValueError("Scene 1 namespaces boundary must not protect or expose endpoints yet")
    if sorted(b_prot.get("managed_namespaces", ())) != namespaces:
        raise ValueError("Scene 1 protected boundary managed_namespaces diverged from namespaces boundary")
    if not protected or b_prot.get("exposed_endpoints") != []:
        raise ValueError("Scene 1 protected boundary must protect endpoints before exposure")
    if sorted(b_ready.get("managed_namespaces", ())) != namespaces:
        raise ValueError("Scene 1 ready boundary managed_namespaces diverged from namespaces boundary")
    if sorted(b_ready.get("protected_endpoints", ())) != protected:
        raise ValueError("Scene 1 ready boundary protected_endpoints diverged from protected boundary")
    if not exposed or not set(exposed) <= set(protected):
        raise ValueError("Scene 1 ready boundary exposed_endpoints must be a non-empty subset of protected_endpoints")

    timestamps = [str(b["observed_at"]) for b in (b_open, b_ns, b_prot, b_ready)]
    clock, to_tick = _clock_and_ticks(timestamps)
    ticks = [to_tick(ts) for ts in timestamps]
    if not (ticks[0] < ticks[1] < ticks[2] < ticks[3]):
        raise ValueError(f"Scene 1 boundary timestamps must be strictly increasing, got {timestamps!r}")

    ns_value = ",".join(namespaces)
    prot_value = ",".join(protected)
    exp_value = ",".join(exposed)
    port_name = SCENE_1_READER_PORT["name"]

    initial = _dated_sweep(
        sweep_id="opening",
        run=run,
        event_time=ticks[0],
        observations=[
            _unknown_observation(
                run=run,
                sweep="opening",
                port=port_name,
                obs_id=f"{port_name}/opening/managed-namespaces",
                subject="prepare-namespaces",
                attribute="managed_namespaces",
                token="startup/managed-namespaces",
                event_time=timestamps[0],
                position=f"opening/{b_open['receipt']}",
                reason=f"opening/{b_open['receipt']}",
            ),
            _unknown_observation(
                run=run,
                sweep="opening",
                port=port_name,
                obs_id=f"{port_name}/opening/protected-endpoints",
                subject="protect-endpoints",
                attribute="protected_endpoints",
                token="startup/protected-endpoints",
                event_time=timestamps[0],
                position=f"opening/{b_open['receipt']}",
                reason=f"opening/{b_open['receipt']}",
            ),
            _unknown_observation(
                run=run,
                sweep="opening",
                port=port_name,
                obs_id=f"{port_name}/opening/exposed-endpoints",
                subject="expose-endpoints",
                attribute="exposed_endpoints",
                token="startup/exposed-endpoints",
                event_time=timestamps[0],
                position=f"opening/{b_open['receipt']}",
                reason=f"opening/{b_open['receipt']}",
            ),
        ],
    )

    sweep_namespaces = _dated_sweep(
        sweep_id="namespaces",
        run=run,
        event_time=ticks[1],
        observations=[
            _known_observation(
                run=run,
                sweep="namespaces",
                port=port_name,
                obs_id=f"{port_name}/namespaces/managed-namespaces",
                subject="prepare-namespaces",
                attribute="managed_namespaces",
                token="startup/managed-namespaces",
                value=ns_value,
                event_time=timestamps[1],
                position=f"namespaces/{b_ns['receipt']}",
                reason=f"namespaces/{b_ns['receipt']}",
            ),
            _unknown_observation(
                run=run,
                sweep="namespaces",
                port=port_name,
                obs_id=f"{port_name}/namespaces/protected-endpoints",
                subject="protect-endpoints",
                attribute="protected_endpoints",
                token="startup/protected-endpoints",
                event_time=timestamps[1],
                position=f"namespaces/{b_ns['receipt']}",
                reason=f"namespaces/{b_ns['receipt']}",
            ),
            _unknown_observation(
                run=run,
                sweep="namespaces",
                port=port_name,
                obs_id=f"{port_name}/namespaces/exposed-endpoints",
                subject="expose-endpoints",
                attribute="exposed_endpoints",
                token="startup/exposed-endpoints",
                event_time=timestamps[1],
                position=f"namespaces/{b_ns['receipt']}",
                reason=f"namespaces/{b_ns['receipt']}",
            ),
        ],
    )

    sweep_protected = _dated_sweep(
        sweep_id="protected",
        run=run,
        event_time=ticks[2],
        observations=[
            _known_observation(
                run=run,
                sweep="protected",
                port=port_name,
                obs_id=f"{port_name}/protected/protected-endpoints",
                subject="protect-endpoints",
                attribute="protected_endpoints",
                token="startup/protected-endpoints",
                value=prot_value,
                event_time=timestamps[2],
                position=f"protected/{b_prot['receipt']}",
                reason=f"protected/{b_prot['receipt']}",
            ),
            _unknown_observation(
                run=run,
                sweep="protected",
                port=port_name,
                obs_id=f"{port_name}/protected/exposed-endpoints",
                subject="expose-endpoints",
                attribute="exposed_endpoints",
                token="startup/exposed-endpoints",
                event_time=timestamps[2],
                position=f"protected/{b_prot['receipt']}",
                reason=f"protected/{b_prot['receipt']}",
            ),
        ],
    )

    sweep_ready = _dated_sweep(
        sweep_id="ready",
        run=run,
        event_time=ticks[3],
        observations=[
            _known_observation(
                run=run,
                sweep="ready",
                port=port_name,
                obs_id=f"{port_name}/ready/exposed-endpoints",
                subject="expose-endpoints",
                attribute="exposed_endpoints",
                token="startup/exposed-endpoints",
                value=exp_value,
                event_time=timestamps[3],
                position=f"ready/{b_ready['receipt']}",
                reason=f"ready/{b_ready['receipt']}",
            ),
        ],
    )

    sha = _std_loop_hash(pack_dir) if pack_sha256 is None else pack_sha256
    recording: dict[str, Any] = {
        "run": run,
        "limit": limit,
        "clock": clock,
        "pack": {"path": pack_path, "sha256": sha},
        "ports": [SCENE_1_READER_PORT, SCENE_1_EFFECT_PORT],
        "records": {
            "loop_active_run": [{"id": run}],
            "loop_step": [
                {"id": "prepare-namespaces", "precedes": ["protect-endpoints"]},
                {"id": "protect-endpoints", "precedes": ["expose-endpoints"]},
                {"id": "expose-endpoints"},
            ],
            "loop_requirement": [
                {
                    "id": "protect-needs-namespaces",
                    "run": run,
                    "step": "protect-endpoints",
                    "token": "startup/managed-namespaces",
                    "reason": "namespaces-before-protection",
                },
                {
                    "id": "expose-needs-protection",
                    "run": run,
                    "step": "expose-endpoints",
                    "token": "startup/protected-endpoints",
                    "reason": "protection-before-exposure",
                },
            ],
            "loop_completion": [
                {
                    "id": "prepare-namespaces-done",
                    "run": run,
                    "step": "prepare-namespaces",
                    "token": "startup/managed-namespaces",
                    "reason": "namespaces-readback",
                },
                {
                    "id": "protect-endpoints-done",
                    "run": run,
                    "step": "protect-endpoints",
                    "token": "startup/protected-endpoints",
                    "reason": "protection-readback",
                },
                {
                    "id": "expose-endpoints-done",
                    "run": run,
                    "step": "expose-endpoints",
                    "token": "startup/exposed-endpoints",
                    "reason": "exposure-readback",
                },
            ],
            "loop_expectation": [
                {"id": "startup/managed-namespaces", "value": ns_value},
                {"id": "startup/protected-endpoints", "value": prot_value},
                {"id": "startup/exposed-endpoints", "value": exp_value},
            ],
        },
        "initial": initial,
        "sweeps": [sweep_namespaces, sweep_protected, sweep_ready],
    }

    plans, outcome, fixed_point = verify_recording_offline(recording, pack_dir=pack_dir)
    expected_plans = [["prepare-namespaces"], ["protect-endpoints"], ["expose-endpoints"]]
    if plans != expected_plans or outcome != "success" or fixed_point:
        raise ValueError(
            f"Scene 1 offline replay mismatch: plans={plans!r}, outcome={outcome!r}, fixed_point={fixed_point!r}"
        )

    manifest: dict[str, Any] = {
        "scene": 1,
        "origin": "real",
        "captured_on": _iso_day(timestamps[3], "Scene 1 ready observed_at"),
        "capture_evidence": f"disposable-cluster:{run}:ready:{b_ready['receipt']}",
        "expected_plans": plans,
        "expected_outcome": outcome,
    }
    return recording, manifest


def build_scene_4_recording(
    events: Sequence[Mapping[str, Any]],
    *,
    pack_path: str = DEFAULT_PACK_PATH,
    pack_sha256: str | None = None,
    limit: int = DEFAULT_LIMIT,
    pack_dir: Path = STD_LOOP_PACK,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert Scene 4 management backup/offline-restore events into a TypedRecording and manifest."""
    if not events:
        raise ValueError("Scene 4 requires recorded management backup events")

    for event in events:
        _verify_management_event_digest(event)
        if event.get("feature") != "backup":
            raise ValueError(f"Scene 4 expected feature='backup', got {event.get('feature')!r}")

    def one(kind: str) -> Mapping[str, Any]:
        matches = [event for event in events if event.get("kind") == kind]
        if len(matches) != 1:
            raise ValueError(f"Scene 4 expected exactly one {kind!r} event, got {len(matches)}")
        return matches[0]

    captured = one("backup-completed")
    binding = one("management-dataset-bound")
    hold = one("management-fence-acquired")
    readback = one("recovered-read")
    coverage = one("management-fence-coverage")
    probes = [event for event in events if event.get("kind") == "management-unreachable"]
    if len(probes) < 2:
        raise ValueError(f"Scene 4 requires opening and closing unreachable probes, got {len(probes)}")
    opening, closing = probes[0], probes[-1]

    run_id = str(captured.get("run", "")).strip()
    attempt = str(captured.get("attempt", "")).strip()
    if not run_id or not attempt:
        raise ValueError("Scene 4 events require non-empty run and attempt identifiers")
    if any(str(e.get("run", "")) != run_id or str(e.get("attempt", "")) != attempt for e in events):
        raise ValueError("Scene 4 events must share the same run and attempt")

    trial = binding.get("trial")
    if not trial or any(e.get("trial") != trial for e in (captured, readback, hold, coverage, *probes)):
        raise ValueError("Scene 4 events must share one non-empty trial identifier")
    if binding.get("dataset") != "management-catalog" or readback.get("dataset") != "management-catalog":
        raise ValueError("Scene 4 dataset must be 'management-catalog'")
    backup_id = str(captured.get("backup", ""))
    if not backup_id or binding.get("backup") != backup_id or readback.get("backup") != backup_id:
        raise ValueError("Scene 4 backup identifier mismatch across capture, binding, and readback")
    if binding.get("source_evidence") != captured["evidence"] or readback.get("source_evidence") != captured["evidence"]:
        raise ValueError("Scene 4 source_evidence mismatch")
    if captured.get("source_cluster") != "management" or readback.get("cluster") != "recovery":
        raise ValueError("Scene 4 requires capture from management and readback in recovery")
    if readback.get("isolated") is not True or readback.get("active_authority") is not False:
        raise ValueError("Scene 4 readback must be isolated without active management authority")

    payload_sha = str(readback.get("payload_sha256", ""))
    if not HEX_64.fullmatch(payload_sha) or captured.get("payload_sha256") != payload_sha or binding.get("payload_sha256") != payload_sha:
        raise ValueError("Scene 4 payload_sha256 mismatch across capture, binding, and readback")

    if any(p.get("cluster") != "management" or p.get("probe_result") != "unreachable" for p in probes):
        raise ValueError("Scene 4 probes must observe management as unreachable")
    fence = str(hold.get("fence", ""))
    if not fence or coverage.get("fence") != fence or coverage.get("fence_evidence") != hold["evidence"]:
        raise ValueError("Scene 4 fence metadata mismatch between hold and coverage")
    if hold.get("cluster") != "management" or coverage.get("cluster") != "management":
        raise ValueError("Scene 4 fence must cover cluster 'management'")
    if coverage.get("complete") is not True or coverage.get("lost") != 0:
        raise ValueError("Scene 4 fence coverage must be complete with zero lost intervals")
    if (
        coverage.get("opening_probe") != opening["evidence"]
        or coverage.get("closing_probe") != closing["evidence"]
        or coverage.get("readback_evidence") != readback["evidence"]
    ):
        raise ValueError("Scene 4 fence coverage references do not match probes or readback")

    hold_index = events.index(hold)
    closing_index = events.index(closing)
    if hold_index >= closing_index:
        raise ValueError("Scene 4 fence acquisition must precede closing probe")
    for event in events[hold_index : closing_index + 1]:
        if event.get("kind") in FORBIDDEN_OUTAGE_KINDS:
            raise ValueError(f"Scene 4 interval broken by forbidden event {event.get('kind')!r}")

    ordered_events = (captured, binding, hold, opening, readback, closing, coverage)
    timestamps = [str(event["observed_at"]) for event in ordered_events]
    clock, to_tick = _clock_and_ticks(timestamps)
    t_cap, t_bind, t_hold, t_open, t_read, t_close, t_cov = (to_tick(ts) for ts in timestamps)
    if not (t_cap <= t_bind < t_hold <= t_open < t_read < t_close <= t_cov):
        raise ValueError(f"Scene 4 event timestamps violate causal order: {timestamps!r}")

    run = f"offline-restore-{run_id}-{attempt}"
    dataset_binding_value = f"{binding['dataset']}:{backup_id}"
    coverage_value = f"{fence}:complete"
    port_name = SCENE_4_READER_PORT["name"]

    initial = _dated_sweep(
        sweep_id="captured",
        run=run,
        event_time=t_bind,
        observations=[
            _known_observation(
                run=run,
                sweep="captured",
                port=port_name,
                obs_id=f"{port_name}/captured/backup-completed",
                subject="management-backup",
                attribute="payload_sha256",
                token="backup/captured",
                value=payload_sha,
                event_time=str(captured["observed_at"]),
                position=f"backup-completed/{captured['evidence']}",
                reason=f"backup-completed/{captured['evidence']}",
            ),
            _known_observation(
                run=run,
                sweep="captured",
                port=port_name,
                obs_id=f"{port_name}/captured/dataset-bound",
                subject="management-backup",
                attribute="dataset_binding",
                token="backup/dataset-bound",
                value=dataset_binding_value,
                event_time=str(binding["observed_at"]),
                position=f"management-dataset-bound/{binding['evidence']}",
                reason=f"management-dataset-bound/{binding['evidence']}",
            ),
            _unknown_observation(
                run=run,
                sweep="captured",
                port=port_name,
                obs_id=f"{port_name}/captured/fence-acquired",
                subject="fence-management",
                attribute="fence",
                token="management/fence-acquired",
                event_time=str(binding["observed_at"]),
                position=f"captured/{binding['evidence']}",
                reason=f"captured/{binding['evidence']}",
            ),
            _unknown_observation(
                run=run,
                sweep="captured",
                port=port_name,
                obs_id=f"{port_name}/captured/management-availability",
                subject="fence-management",
                attribute="availability",
                token="management/availability",
                event_time=str(binding["observed_at"]),
                position=f"captured/{binding['evidence']}",
                reason=f"captured/{binding['evidence']}",
            ),
            _unknown_observation(
                run=run,
                sweep="captured",
                port=port_name,
                obs_id=f"{port_name}/captured/recovered-payload",
                subject="restore-copy",
                attribute="payload_sha256",
                token="management-copy/payload",
                event_time=str(binding["observed_at"]),
                position=f"captured/{binding['evidence']}",
                reason=f"captured/{binding['evidence']}",
            ),
            _unknown_observation(
                run=run,
                sweep="captured",
                port=port_name,
                obs_id=f"{port_name}/captured/fence-coverage",
                subject="verify-fence-coverage",
                attribute="coverage",
                token="management/fence-coverage",
                event_time=str(binding["observed_at"]),
                position=f"captured/{binding['evidence']}",
                reason=f"captured/{binding['evidence']}",
            ),
        ],
    )

    sweep_fenced = _dated_sweep(
        sweep_id="fenced",
        run=run,
        event_time=t_open,
        observations=[
            _known_observation(
                run=run,
                sweep="fenced",
                port=port_name,
                obs_id=f"{port_name}/fenced/fence-acquired",
                subject="fence-management",
                attribute="fence",
                token="management/fence-acquired",
                value=fence,
                event_time=str(hold["observed_at"]),
                position=f"management-fence-acquired/{hold['evidence']}",
                reason=f"management-fence-acquired/{hold['evidence']}",
            ),
            _known_observation(
                run=run,
                sweep="fenced",
                port=port_name,
                obs_id=f"{port_name}/fenced/opening-unreachable",
                subject="fence-management",
                attribute="availability",
                token="management/availability",
                value="unreachable",
                event_time=str(opening["observed_at"]),
                position=f"management-unreachable-opening/{opening['evidence']}",
                reason=f"management-unreachable-opening/{opening['evidence']}",
            ),
        ],
    )

    sweep_restored = _dated_sweep(
        sweep_id="restored",
        run=run,
        event_time=t_read,
        observations=[
            _known_observation(
                run=run,
                sweep="restored",
                port=port_name,
                obs_id=f"{port_name}/restored/recovered-read",
                subject="restore-copy",
                attribute="payload_sha256",
                token="management-copy/payload",
                value=payload_sha,
                event_time=str(readback["observed_at"]),
                position=f"recovered-read/{readback['evidence']}",
                reason=f"recovered-read/{readback['evidence']}",
            ),
        ],
    )

    sweep_verified = _dated_sweep(
        sweep_id="verified",
        run=run,
        event_time=t_cov,
        observations=[
            _known_observation(
                run=run,
                sweep="verified",
                port=port_name,
                obs_id=f"{port_name}/verified/closing-unreachable",
                subject="verify-fence-coverage",
                attribute="availability",
                token="management/availability",
                value="unreachable",
                event_time=str(closing["observed_at"]),
                position=f"management-unreachable-closing/{closing['evidence']}",
                reason=f"management-unreachable-closing/{closing['evidence']}",
            ),
            _known_observation(
                run=run,
                sweep="verified",
                port=port_name,
                obs_id=f"{port_name}/verified/fence-coverage",
                subject="verify-fence-coverage",
                attribute="coverage",
                token="management/fence-coverage",
                value=coverage_value,
                event_time=str(coverage["observed_at"]),
                position=f"management-fence-coverage/{coverage['evidence']}",
                reason=f"management-fence-coverage/{coverage['evidence']}",
            ),
        ],
    )

    sha = _std_loop_hash(pack_dir) if pack_sha256 is None else pack_sha256
    recording: dict[str, Any] = {
        "run": run,
        "limit": limit,
        "clock": clock,
        "pack": {"path": pack_path, "sha256": sha},
        "ports": [SCENE_4_READER_PORT, SCENE_4_EFFECT_PORT],
        "records": {
            "loop_active_run": [{"id": run}],
            "loop_step": [
                {"id": "fence-management", "precedes": ["restore-copy"]},
                {"id": "restore-copy", "precedes": ["verify-fence-coverage"]},
                {"id": "verify-fence-coverage"},
            ],
            "loop_requirement": [
                {
                    "id": "fence-needs-backup",
                    "run": run,
                    "step": "fence-management",
                    "token": "backup/captured",
                    "reason": "backup-captured",
                },
                {
                    "id": "fence-needs-binding",
                    "run": run,
                    "step": "fence-management",
                    "token": "backup/dataset-bound",
                    "reason": "dataset-bound",
                },
                {
                    "id": "restore-needs-fence",
                    "run": run,
                    "step": "restore-copy",
                    "token": "management/fence-acquired",
                    "reason": "fence-acquired",
                },
                {
                    "id": "restore-needs-offline",
                    "run": run,
                    "step": "restore-copy",
                    "token": "management/availability",
                    "reason": "management-offline",
                },
                {
                    "id": "coverage-needs-readback",
                    "run": run,
                    "step": "verify-fence-coverage",
                    "token": "management-copy/payload",
                    "reason": "recovered-readback",
                },
                {
                    "id": "coverage-needs-offline",
                    "run": run,
                    "step": "verify-fence-coverage",
                    "token": "management/availability",
                    "reason": "management-offline",
                },
            ],
            "loop_completion": [
                {
                    "id": "fence-management-done",
                    "run": run,
                    "step": "fence-management",
                    "token": "management/availability",
                    "reason": "opening-unreachable-probe",
                },
                {
                    "id": "restore-copy-done",
                    "run": run,
                    "step": "restore-copy",
                    "token": "management-copy/payload",
                    "reason": "isolated-readback",
                },
                {
                    "id": "verify-fence-coverage-done",
                    "run": run,
                    "step": "verify-fence-coverage",
                    "token": "management/fence-coverage",
                    "reason": "complete-fence-coverage",
                },
            ],
            "loop_expectation": [
                {"id": "backup/captured", "value": payload_sha},
                {"id": "backup/dataset-bound", "value": dataset_binding_value},
                {"id": "management/fence-acquired", "value": fence},
                {"id": "management/availability", "value": "unreachable"},
                {"id": "management-copy/payload", "value": payload_sha},
                {"id": "management/fence-coverage", "value": coverage_value},
            ],
        },
        "initial": initial,
        "sweeps": [sweep_fenced, sweep_restored, sweep_verified],
    }

    plans, outcome, fixed_point = verify_recording_offline(recording, pack_dir=pack_dir)
    expected_plans = [["fence-management"], ["restore-copy"], ["verify-fence-coverage"]]
    if plans != expected_plans or outcome != "success" or fixed_point:
        raise ValueError(
            f"Scene 4 offline replay mismatch: plans={plans!r}, outcome={outcome!r}, fixed_point={fixed_point!r}"
        )

    manifest: dict[str, Any] = {
        "scene": 4,
        "origin": "real",
        "captured_on": _iso_day(str(coverage["observed_at"]), "Scene 4 coverage observed_at"),
        "capture_evidence": (
            f"disposable-cluster:record-backup-{run_id}-{attempt}:coverage:{coverage['evidence']}"
        ),
        "expected_plans": plans,
        "expected_outcome": outcome,
    }
    return recording, manifest


def _default_run_cmd(args: Sequence[str], *, timeout: int = 30) -> str:
    return subprocess.run(
        list(args),
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        timeout=timeout,
    ).stdout


class ClusterRecorderReader:
    """Read completed Scene 1 boundary and Scene 4 backup recorder Jobs from the disposable cluster."""

    def __init__(
        self,
        kubeconfig: Path,
        *,
        context: str = CONTEXT,
        env: Mapping[str, str] | None = None,
        runner: Callable[..., str] | None = None,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.runner = _default_run_cmd if runner is None else runner
        config = Path(kubeconfig).resolve(strict=True)
        base = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
        if self.runner([*base, "config", "current-context"], timeout=25).strip() != context:
            raise RuntimeError(f"unexpected kubectl current-context; expected {context!r}")
        server = self.runner(
            [*base, "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"],
            timeout=25,
        ).strip()
        host = urlsplit(server).hostname
        if not host or (host != "localhost" and not ip_address(host).is_loopback):
            raise RuntimeError("disposable cluster API server must be runner-local")
        self.command = [*base, "--context", context]

    def _get_json(self, *args: str, namespace: str | None = PROBE_NAMESPACE) -> dict[str, Any]:
        cmd = [*self.command, *(["-n", namespace] if namespace else []), "get", *args, "-o", "json"]
        return json.loads(self.runner(cmd, timeout=25))

    def _read_recorder_job_jsonl(self, job: Mapping[str, Any]) -> list[dict[str, Any]]:
        name = job["metadata"]["name"]
        uid = job["metadata"]["uid"]
        if job.get("status", {}).get("succeeded") != 1:
            raise RuntimeError(f"recorder Job {name!r} did not succeed")
        pods = self._get_json("pods", "-l", f"job-name={name}").get("items") or []
        succeeded = [
            pod
            for pod in pods
            if (pod.get("status") or {}).get("phase") == "Succeeded"
            and any(
                owner.get("uid") == uid and owner.get("controller")
                for owner in (pod.get("metadata", {}).get("ownerReferences") or ())
            )
        ]
        if len(succeeded) != 1:
            raise RuntimeError(f"expected one succeeded Pod for recorder Job {name!r}, found {len(succeeded)}")
        pod_name = succeeded[0]["metadata"]["name"]
        logs = self.runner(
            [*self.command, "-n", PROBE_NAMESPACE, "logs", pod_name, "-c", "recorder"],
            timeout=25,
        )
        return [json.loads(line) for line in logs.splitlines() if line.strip()]

    def read_startup_boundaries(self, startup_run: str | None = None) -> list[dict[str, Any]] | None:
        selector = f"{ROLE_LABEL}={BOUNDARY_ROLE}"
        run_filter = startup_run
        if not run_filter and self.env.get("GITHUB_RUN_ID") and self.env.get("GITHUB_RUN_ATTEMPT"):
            run_filter = f"safe-start-{self.env['GITHUB_RUN_ID']}-{self.env['GITHUB_RUN_ATTEMPT']}"
        if run_filter:
            selector = f"{RUN_LABEL}={run_filter},{selector}"
        jobs = self._get_json("jobs", "-l", selector).get("items") or []
        if not jobs:
            return None
        if not run_filter:
            runs = {job.get("metadata", {}).get("labels", {}).get(RUN_LABEL, "") for job in jobs}
            runs.discard("")
            if len(runs) != 1:
                raise RuntimeError(f"expected one safe-start run in {PROBE_NAMESPACE}, found {sorted(runs)!r}")
        boundaries: list[dict[str, Any]] = []
        for job in jobs:
            rows = self._read_recorder_job_jsonl(job)
            if len(rows) != 1:
                raise RuntimeError(
                    f"expected one boundary event from Job {job['metadata']['name']!r}, got {len(rows)}"
                )
            boundaries.append(rows[0])
        order = {cut: index for index, cut in enumerate(SCENE_1_CUTS)}
        boundaries.sort(key=lambda item: order.get(str(item.get("cut")), len(SCENE_1_CUTS)))
        return boundaries

    def read_backup_events(self) -> list[dict[str, Any]] | None:
        run_id = self.env.get("GITHUB_RUN_ID", "")
        attempt = self.env.get("GITHUB_RUN_ATTEMPT", "")
        if run_id and attempt:
            selector = f"{MANAGEMENT_FEATURE_LABEL}=backup,{RECORDER_RUN_LABEL}={run_id}-{attempt}"
        else:
            selector = f"{MANAGEMENT_FEATURE_LABEL}=backup"
        jobs = self._get_json("jobs", "-l", selector).get("items") or []
        if not jobs:
            return None
        if len(jobs) != 1:
            raise RuntimeError(f"expected one management backup recorder Job, found {len(jobs)}")
        return self._read_recorder_job_jsonl(jobs[0])


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, allow_nan=False) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def export_recordings(
    out_dir: Path,
    *,
    reader: ClusterRecorderReader,
    pack_path: str = DEFAULT_PACK_PATH,
    require_all: bool = False,
    startup_run: str | None = None,
    pack_dir: Path = STD_LOOP_PACK,
) -> dict[int, tuple[Path, Path]]:
    """Read live cluster evidence and export validated Scene 1 and Scene 4 TypedRecordings."""
    exported: dict[int, tuple[Path, Path]] = {}

    boundaries = reader.read_startup_boundaries(startup_run=startup_run)
    if boundaries is not None:
        recording, manifest = build_scene_1_recording(boundaries, pack_path=pack_path, pack_dir=pack_dir)
        rec_path = out_dir / "scene-1-recording.json"
        man_path = out_dir / "scene-1-manifest.json"
        _write_json(rec_path, recording)
        _write_json(man_path, manifest)
        exported[1] = (rec_path, man_path)
    elif require_all:
        raise RuntimeError("Scene 1 live startup boundary recorder Jobs were not found in the disposable cluster")

    backup_events = reader.read_backup_events()
    if backup_events is not None:
        recording, manifest = build_scene_4_recording(backup_events, pack_path=pack_path, pack_dir=pack_dir)
        rec_path = out_dir / "scene-4-recording.json"
        man_path = out_dir / "scene-4-manifest.json"
        _write_json(rec_path, recording)
        _write_json(man_path, manifest)
        exported[4] = (rec_path, man_path)
    elif require_all:
        raise RuntimeError("Scene 4 live management backup recorder Job was not found in the disposable cluster")

    if not exported:
        raise RuntimeError("No Scene 1 or Scene 4 live recordings were found in the disposable cluster")
    return exported


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="Directory to write exported scene recordings.")
    parser.add_argument(
        "--kubeconfig",
        type=Path,
        default=None,
        help="Path to the disposable cluster kubeconfig (defaults to REZONO_CLUSTER_KUBECONFIG or KUBECONFIG).",
    )
    parser.add_argument(
        "--pack-path",
        default=DEFAULT_PACK_PATH,
        help=f"Relative std-loop pack path stored in recording.json (default: {DEFAULT_PACK_PATH}).",
    )
    parser.add_argument(
        "--startup-run",
        default=None,
        help="Optional rezono.org/safe-start-run label value for Scene 1 boundary Jobs.",
    )
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Fail unless both Scene 1 and Scene 4 live recordings are present and exported.",
    )
    args = parser.parse_args(argv)

    kubeconfig = args.kubeconfig
    if kubeconfig is None:
        raw_kubeconfig = os.environ.get("REZONO_CLUSTER_KUBECONFIG") or os.environ.get("KUBECONFIG")
        if not raw_kubeconfig:
            parser.error("--kubeconfig is required when REZONO_CLUSTER_KUBECONFIG and KUBECONFIG are unset")
        kubeconfig = Path(raw_kubeconfig)

    reader = ClusterRecorderReader(kubeconfig)
    exported = export_recordings(
        args.out_dir,
        reader=reader,
        pack_path=args.pack_path,
        require_all=args.require_all,
        startup_run=args.startup_run,
    )
    for scene in sorted(exported):
        rec_path, man_path = exported[scene]
        print(f"Exported scene {scene}: {rec_path} ({man_path})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
