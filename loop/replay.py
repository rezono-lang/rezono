"""Replay the reconciliation frontier against recorded, run-scoped sweeps."""

from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from itertools import chain
from pathlib import Path
from typing import Any, Literal, cast

from rezono_compiler import batch, facts, pack, rules, scenarios

from loop.frontier import frontier
from loop.round_limit import can_continue

RESERVED_STATES = frozenset({"applying", "unknown"})
RELEASED_STATES = frozenset({"failed", "cleaned"})
_UNBLOCKED_RELATIONS = ("declared", "unblocked", "done", "stuck", "drift", "round_outcome")


@cache
def _loop_theory() -> tuple[pack.Pack, rules.Program]:
    path = Path(__file__).resolve().parents[1] / "packs" / "std-loop"
    model = pack.read(path)
    return model, rules.load(model.rules)


def _require_round_outcome(snapshot: "Snapshot") -> Literal["success", "pending", "failure"]:
    if snapshot.round_outcome is None:
        raise ValueError("snapshot is missing round outcome")
    return snapshot.round_outcome


def snapshot_from_rows(
    run: str,
    selected: Mapping[str, Collection[tuple[str, ...]]],
    *,
    frontier_relation: Literal["unblocked", "ready"] = "unblocked",
) -> "Snapshot":
    """Build one run-scoped Snapshot from selected std-loop relations."""
    outcomes = {row[1] for row in selected["round_outcome"]}
    if len(outcomes) != 1 or not outcomes <= {"pending", "success", "failure"}:
        raise ValueError(f"expected one round outcome for {run!r}, got {sorted(outcomes)}")
    round_outcome = cast(Literal["success", "pending", "failure"], next(iter(outcomes)))
    return Snapshot(
        {row[1] for row in selected["declared"]},
        cast(Collection[tuple[str, str, str]], selected[frontier_relation]),
        {row[1] for row in selected["done"]},
        {row[1] for row in selected["stuck"]},
        selected["drift"],
        cast(Collection[tuple[str, str, str, str, str]], selected.get("fixed_point", ())),
        round_outcome,
    )


@dataclass
class Snapshot:
    declared: set[str]
    ready: Collection[tuple[str, str, str]]
    done: set[str]
    stuck: set[str]
    drift: Collection[object]
    fixed_point: Collection[tuple[str, str, str, str, str]] = ()
    round_outcome: Literal["success", "pending", "failure"] | None = None


def replay_report(run: str, limit: int, snapshots: Iterator[Snapshot], *, report_limit: bool):
    """Execute a frontier, consume one full sweep and decide again on its resulting state."""
    can_continue(0, limit, ())
    trace: list[list[str]] = []
    current = next(snapshots)
    while True:
        state = _require_round_outcome(current)
        if current.fixed_point:
            return trace, "failure", sorted(current.fixed_point)
        if state != "pending":
            return trace, state, []
        plans = list(frontier(run, current.ready, {step: step for step in current.declared}))
        if report_limit and len(trace) == limit:
            return trace, "failure", []
        can_continue(len(trace), limit, current.declared - current.done)
        following = next(snapshots, None)
        if following is None:
            return trace, "pending" if report_limit else "failure", []
        trace.append(plans)
        current = following


def replay_certified_report(
    run: str,
    limit: int,
    snapshots: Iterator[Snapshot],
    certified_rounds: Sequence[Any],
    *,
    report_limit: bool,
):
    """Execute certified frontiers while preserving durable claims and uncertain-attempt reservations."""
    can_continue(0, limit, ())
    trace: list[list[str]] = []
    submissions: list[dict[str, str]] = []
    round_reports: list[dict[str, Any]] = []
    claimed: dict[str, str] = {}
    reserved: dict[str, str] = {}
    reserved_state: dict[str, str] = {}
    round_iter = iter(certified_rounds)

    def record_round(current_round: Any, current: Snapshot) -> None:
        round_reports.append({
            "run": current_round.run,
            "cut": current_round.cut,
            "done": sorted(current.done),
            "reserved": sorted(reserved),
        })

    current = next(snapshots)
    current_round = next(round_iter)
    while True:
        for attempt in current_round.attempts:
            if attempt.plan_hash in reserved:
                reserved_step = reserved[attempt.plan_hash]
                if attempt.step != reserved_step:
                    raise ValueError(
                        f"attempt plan_hash {attempt.plan_hash!r} is reserved for step "
                        f"{reserved_step!r}, not {attempt.step!r}"
                    )
                reserved_state[attempt.plan_hash] = attempt.state
            elif attempt.plan_hash in claimed and claimed[attempt.plan_hash] != attempt.step:
                raise ValueError(
                    f"attempt plan_hash {attempt.plan_hash!r} is claimed for step "
                    f"{claimed[attempt.plan_hash]!r}, not {attempt.step!r}"
                )

        for plan_hash, step in list(reserved.items()):
            attempt_state = reserved_state[plan_hash]
            if (attempt_state == "applied" and step in current.done) or attempt_state in RELEASED_STATES:
                reserved.pop(plan_hash)
                reserved_state.pop(plan_hash)

        state = _require_round_outcome(current)
        if current.fixed_point:
            record_round(current_round, current)
            return trace, "failure", sorted(current.fixed_point), submissions, round_reports
        if state != "pending":
            record_round(current_round, current)
            return trace, state, [], submissions, round_reports

        reserved_steps = set(reserved.values())
        ready_unreserved = [row for row in current.ready if row[1] not in reserved_steps]
        plans = list(frontier(run, ready_unreserved, {step: step for step in current.declared}))
        if report_limit and len(trace) == limit:
            record_round(current_round, current)
            return trace, "failure", [], submissions, round_reports
        can_continue(len(trace), limit, current.declared - current.done)

        following = next(snapshots, None)
        if following is None:
            record_round(current_round, current)
            return trace, "pending" if report_limit else "failure", [], submissions, round_reports

        for step in plans:
            for attempt in current_round.attempts:
                if attempt.step != step:
                    continue
                if attempt.plan_hash in claimed:
                    if claimed[attempt.plan_hash] != step:
                        raise ValueError(
                            f"attempt plan_hash {attempt.plan_hash!r} is claimed for step "
                            f"{claimed[attempt.plan_hash]!r}, not {step!r}"
                        )
                    continue
                claimed[attempt.plan_hash] = step
                submissions.append({"step": step, "plan_hash": attempt.plan_hash})
                if attempt.state in RESERVED_STATES or (attempt.state == "applied" and step not in current.done):
                    reserved[attempt.plan_hash] = step
                    reserved_state[attempt.plan_hash] = attempt.state

        record_round(current_round, current)
        trace.append(plans)
        current = following
        current_round = next(round_iter)


def replay_snapshots(run: str, limit: int, snapshots: Iterator[Snapshot], *, report_limit: bool):
    plans, state, _ = replay_report(run, limit, snapshots, report_limit=report_limit)
    return plans, state


def _untyped_records(
    run: str,
    requirements: Mapping[str, Collection[str]],
    completion: Mapping[str, str],
) -> tuple[dict[str, list[dict[str, object]]], set[str]]:
    """Build base std-loop records for an untyped recording."""
    completions = [
        {
            "id": f"completion-{step}",
            "run": run,
            "step": step,
            "token": token,
            "reason": f"completion-{step}",
        }
        for step, token in sorted(completion.items())
    ]
    reqs = []
    tokens = set(completion.values())
    for step in sorted(requirements):
        for token in requirements[step]:
            idx = len(reqs)
            reqs.append({
                "id": f"requirement-{idx}",
                "run": run,
                "step": step,
                "token": token,
                "reason": f"requirement-{idx}",
            })
            tokens.add(token)
    records: dict[str, list[dict[str, object]]] = {
        "loop_active_run": [{"id": run}],
        "loop_step": [{"id": step} for step in sorted(requirements)],
        "loop_completion": completions,
        "loop_requirement": reqs,
        "loop_expectation": [{"id": token, "value": "known"} for token in sorted(tokens)],
        "loop_observation": [],
    }
    return records, tokens


def replay(
    run: str,
    requirements: Mapping[str, Collection[str]],
    completion: Mapping[str, str],
    initial: Iterable[Sequence[str]],
    sweeps: Iterable[Iterable[Sequence[str]]],
    limit: int,
) -> tuple[list[list[str]], Literal["success", "failure"]]:
    """Replay normalized token evidence and return each emitted frontier and the outcome."""
    can_continue(0, limit, ())
    if requirements.keys() != completion.keys():
        raise ValueError("each declared step needs one completion token")

    model, program = _loop_theory()
    base_records, expected_tokens = _untyped_records(run, requirements, completion)

    def snapshots() -> Iterator[Snapshot]:
        observations: list[dict[str, object]] = []
        expectations = list(base_records["loop_expectation"])
        seen_tokens = set(expected_tokens)
        for sweep_index, evidence in enumerate(chain((initial,), sweeps)):
            for row_run, token, reason in evidence:
                if token not in seen_tokens:
                    seen_tokens.add(token)
                    expectations.append({"id": token, "value": "known"})
                observations.append({
                    "id": f"observation-{len(observations)}",
                    "run": row_run,
                    "token": token,
                    "event_time": sweep_index,
                    "state": "known",
                    "value": "known",
                    "reason": reason,
                })
            records = {
                **base_records,
                "loop_expectation": expectations,
                "loop_observation": observations,
            }
            inputs = scenarios.rule_rows(model, program, facts.rows_of(model, records))
            with batch.connect(program, inputs) as connection:
                batch.compute(connection, program)
                rows = batch.read(connection, program, _UNBLOCKED_RELATIONS)
            selected = {
                name: {row for row in relation if row[0] == run}
                for name, relation in rows.items()
            }
            yield snapshot_from_rows(run, selected)

    return replay_snapshots(run, limit, snapshots(), report_limit=False)
