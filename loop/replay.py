"""Replay the reconciliation frontier against recorded, run-scoped sweeps."""

from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain
from typing import Literal

from loop.frontier import frontier
from loop.round_limit import can_continue
from loop.round_outcome import outcome


@dataclass
class Snapshot:
    declared: set[str]
    ready: Collection[tuple[str, str, str]]
    done: set[str]
    stuck: set[str]
    drift: Collection[object]


def replay_snapshots(run: str, limit: int, snapshots: Iterator[Snapshot], *, report_limit: bool):
    """Execute a frontier, consume one full sweep and decide again on its resulting state."""
    can_continue(0, limit, ())
    trace: list[list[str]] = []
    current = next(snapshots)
    while True:
        state = outcome(declared=current.declared, done=current.done, stuck=current.stuck, drift=current.drift)
        if state != "pending":
            return trace, state
        plans = list(frontier(run, current.ready, {step: step for step in current.declared}))
        if not plans or (report_limit and len(trace) == limit):
            return trace, "failure"
        can_continue(len(trace), limit, current.declared - current.done)
        following = next(snapshots, None)
        if following is None:
            return trace, "failure"
        trace.append(plans)
        current = following


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
