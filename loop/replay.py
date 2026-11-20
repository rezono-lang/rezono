"""Replay the reconciliation frontier against recorded, run-scoped sweeps."""

from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from typing import Any, Literal

from loop.frontier import frontier
from loop.round_limit import can_continue
from loop.round_outcome import outcome

RESERVED_STATES = frozenset({"applying", "unknown"})
RELEASED_STATES = frozenset({"failed", "cleaned"})


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
        state = (
            current.round_outcome
            if current.round_outcome is not None
            else outcome(declared=current.declared, done=current.done, stuck=current.stuck, drift=current.drift)
        )
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
    claimed: set[str] = set()
    reserved: dict[str, str] = {}
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
                if (attempt.state == "applied" and attempt.step in current.done) or attempt.state in RELEASED_STATES:
                    reserved.pop(attempt.plan_hash, None)

        state = (
            current.round_outcome
            if current.round_outcome is not None
            else outcome(declared=current.declared, done=current.done, stuck=current.stuck, drift=current.drift)
        )
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
                if attempt.step != step or attempt.plan_hash in claimed:
                    continue
                claimed.add(attempt.plan_hash)
                submissions.append({"step": step, "plan_hash": attempt.plan_hash})
                if attempt.state in RESERVED_STATES:
                    reserved[attempt.plan_hash] = step

        record_round(current_round, current)
        trace.append(plans)
        current = following
        current_round = next(round_iter)


def replay_snapshots(run: str, limit: int, snapshots: Iterator[Snapshot], *, report_limit: bool):
    plans, state, _ = replay_report(run, limit, snapshots, report_limit=report_limit)
    return plans, state


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

    def snapshots():
        known = set()
        declared = set(requirements)
        for evidence in chain((initial,), sweeps):
            known.update(token for row_run, token, _ in evidence if row_run == run)
            done = {step for step, token in completion.items() if token in known}
            ready = [(run, step, step) for step in declared - done if known.issuperset(requirements[step])]
            yield Snapshot(declared, ready, done, set(), ())

    return replay_snapshots(run, limit, snapshots(), report_limit=False)
