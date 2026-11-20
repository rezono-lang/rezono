"""Execute planned loop frontiers, read back dated sweeps and record a replayable run."""

from collections.abc import Callable, Iterator
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from loop.frontier import frontier
from loop.replay import Snapshot, replay_report
from loop.typed_recording import Sweep, read_sweep, typed_recording

REQUIRED_KEYS = frozenset({"run", "limit", "initial", "ports", "pack", "records"})
OPTIONAL_KEYS = frozenset({"sweeps", "clock"})
FIXED_POINT_COLUMNS = ("run", "sweep", "step", "token", "requirement")


def _plain_json(value: Any, label: str) -> Any:
    try:
        copied = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be plain JSON") from error
    if copied != value:
        raise ValueError(f"{label} must be plain JSON")
    return copied


def execute(
    directory: str | Path,
    data: dict[str, Any],
    *,
    apply: Callable[[str, int, str], Any],
    read: Callable[[str, int], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate the pinned std-loop pack, apply ready steps, read back sweeps and return report and recording."""
    if not isinstance(data, dict) or not (REQUIRED_KEYS <= set(data) <= (REQUIRED_KEYS | OPTIONAL_KEYS)):
        raise ValueError("recording must contain run, limit, initial, ports, pack and records")
    run, limit = data["run"], data["limit"]
    if not isinstance(run, str) or not run.strip() or type(limit) is not int or limit <= 0:
        raise ValueError("recording requires a run ID and a positive integer round limit")
    if "sweeps" in data and (not isinstance(data["sweeps"], list) or data["sweeps"]):
        raise ValueError("sweeps must be empty or absent before execution")
    if not isinstance(data["records"], dict):
        raise ValueError("records must be an object")

    base_data = _plain_json(deepcopy(data), "recording")
    recording = typed_recording(Path(directory), {**base_data, "sweeps": []})

    effects = [port["name"] for port in base_data["ports"] if port["kind"] == "effect"]
    readers = {
        port["name"]
        for port in base_data["ports"]
        if port["kind"] == "in" and "loop_observation" in port["produces"]
    }
    if len(effects) != 1 or not readers:
        raise ValueError("execution requires one effect port and at least one loop_observation reader")

    from rezono_compiler import facts

    admitted = facts.rows_of(recording.model, recording.records)
    expectations = {token for token, _ in admitted.get("loop_expectation__value", ())}

    identities: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
    for event in recording.rounds[0].events:
        observation = event.envelope["observation"]
        key = (event.envelope["run"], observation["id"])
        identities[key] = (observation, event.envelope["reason"])
    sweep_ids: set[tuple[str, str]] = set()
    latest_boundary: dict[str, int] = {}
    recorded_sweeps: list[dict[str, Any]] = []

    def admit_sweep(raw: Any) -> tuple[dict[str, Any], Sweep]:
        if not isinstance(raw, dict):
            raise ValueError("read must return a dated sweep")
        plain = _plain_json(raw, "dated sweep")
        sweep = read_sweep(plain, readers, expectations)
        if plain["run"] != run:
            raise ValueError(f"dated sweep belongs to run {plain['run']!r}, expected {run!r}")
        sweep_key = (plain["run"], plain["id"])
        if sweep_key in sweep_ids:
            raise ValueError(f"duplicate dated sweep {sweep_key!r}")
        if plain["run"] in latest_boundary and plain["event_time"] < latest_boundary[plain["run"]]:
            raise ValueError("dated sweeps must follow event-time order within a run")
        staged = dict(identities)
        for event in sweep.events:
            observation = event.envelope["observation"]
            key = (event.envelope["run"], observation["id"])
            identity = (observation, event.envelope["reason"])
            if staged.setdefault(key, identity) != identity:
                raise ValueError(f"conflicting observations with event ID {key[1]!r}")
        identities.update(staged)
        sweep_ids.add(sweep_key)
        latest_boundary[plain["run"]] = plain["event_time"]
        return plain, sweep

    raw_snapshots = recording.snapshots()
    last_snapshot: list[Snapshot] = []

    def driven_snapshots() -> Iterator[Snapshot]:
        current = next(raw_snapshots)
        last_snapshot[:] = [current]
        yield current
        round_number = 0
        while True:
            round_number += 1
            step_plans = list(frontier(run, current.ready, {step: step for step in current.declared}))
            for step in step_plans:
                apply(run, round_number, step)
            plain_sweep, sweep = admit_sweep(read(run, round_number))
            recorded_sweeps.append(plain_sweep)
            recording.rounds.append(sweep)
            current = next(raw_snapshots)
            last_snapshot[:] = [current]
            yield current

    plans, outcome, fixed_point = replay_report(run, limit, driven_snapshots(), report_limit=True)

    findings = [
        {"token": token, "desired": desired, "observed": observed}
        for _, token, desired, observed in sorted(last_snapshot[0].drift)
    ]
    report: dict[str, Any] = {
        "plans": plans,
        "outcome": outcome,
        "rounds": len(plans),
        "findings": findings,
    }
    if fixed_point:
        report["fixed_point"] = [dict(zip(FIXED_POINT_COLUMNS, row, strict=True)) for row in fixed_point]

    return report, {**base_data, "sweeps": recorded_sweeps}
