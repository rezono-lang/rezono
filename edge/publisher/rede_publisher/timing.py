"""Time per phase of one publication, for the log and the CI step summary only (never in a published object:
the store gets the same bytes whatever the clock says, AGENTS.md rule 3).

A monotonic clock, and every moment counts toward exactly one phase: `switch` names the phase from here on,
`phase` lends the time of a block to another phase (the checker inside the views, say) and gives it back.
So the phases add up to the whole run, and a share is a share of that.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager

# The order of the report; a phase not named here comes after them, by name.
PHASES = ("compile", "batch", "filter", "checker", "tiles", "views", "upload", "manifest")

_spent: dict[str, float] = {}
_stack: list[list] = []  # [phase, since]: the innermost last


def _credit(now: float) -> None:
    if _stack:
        name, since = _stack[-1]
        _spent[name] = _spent.get(name, 0.0) + now - since


def switch(name: str) -> None:
    """From now on the time counts toward `name` (until the next switch, or the end of an enclosing `phase`)."""
    now = time.monotonic()
    _credit(now)
    if _stack:
        _stack[-1] = [name, now]
    else:
        _stack.append([name, now])


@contextmanager
def phase(name: str):
    """The time of this block counts toward `name`; afterwards the phase before it goes on."""
    now = time.monotonic()
    _credit(now)
    _stack.append([name, now])
    try:
        yield
    finally:
        now = time.monotonic()
        _credit(now)
        _stack.pop()
        if _stack:
            _stack[-1][1] = now


def spent() -> dict[str, float]:
    """Seconds per phase so far, in the order of the report."""
    _credit(time.monotonic())
    if _stack:
        _stack[-1][1] = time.monotonic()
    order = [p for p in PHASES if p in _spent] + sorted(set(_spent) - set(PHASES))
    return {p: _spent[p] for p in order}


def report(label: str, out=sys.stderr, summary: str | None = None) -> dict[str, float]:
    """Write the seconds per phase: one line per phase to `out` (the log), and a table to the step summary
    (`$GITHUB_STEP_SUMMARY`, if set). Then start again from nothing. Returns what was reported."""
    times = spent()
    _spent.clear()
    _stack.clear()
    total = sum(times.values())
    share = lambda s: f"{100 * s / total:.1f}%" if total else "–"
    lines = [f"time {label} {p} {s:.3f}s {share(s)}" for p, s in times.items()] + [f"time {label} total {total:.3f}s"]
    print("\n".join(lines), file=out)
    # The same lines for deploy/profiles/edge/publish.sh, which names the slowest pack's largest phase when the
    # profile is over its time budget (RV-Z11; deploy/profiles/edge/budget.py). A log, never the store.
    if os.environ.get("REDE_TIMES_FILE"):
        with open(os.environ["REDE_TIMES_FILE"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    path = summary if summary is not None else os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        largest = max(times, key=times.get) if times else None
        lines = [f"### Publication time: {label}", "", "| phase | seconds | share |", "|---|---:|---:|"]
        lines += [f"| {'**' + p + '**' if p == largest else p} | {s:.2f} | {share(s)} |" for p, s in times.items()]
        lines += [f"| total | {total:.2f} | |", ""]
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return times
