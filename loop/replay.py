"""Replay the reconciliation frontier against recorded, run-scoped sweeps."""

from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Literal

from loop.frontier import frontier
from loop.round_limit import can_continue
from loop.round_outcome import outcome


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

    known = {token for row_run, token, _ in initial if row_run == run}
    plans = {step: step for step in requirements}
    trace: list[list[str]] = []
    recorded = iter(sweeps)
    while True:
        done = {step for step, token in completion.items() if token in known}
        pending = requirements.keys() - done
        ready = {step for step in pending if known.issuperset(requirements[step])}
        # A recording has no separate in-flight operation that could advance a stalled frontier.
        stuck = pending if not ready else set()
        state = outcome(declared=requirements.keys(), done=done, stuck=stuck, drift=())
        if state != "pending":
            return trace, state
        can_continue(len(trace), limit, pending)
        sweep = next(recorded, None)
        if sweep is None:
            return trace, "failure"
        trace.append(list(frontier(run, ((run, step, step) for step in ready), plans)))
        known.update(token for row_run, token, _ in sweep if row_run == run)
