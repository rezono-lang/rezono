"""Select the plans for the recorded ready steps of one run."""

from collections.abc import Iterable, Iterator, Mapping
from typing import TypeVar

Plan = TypeVar("Plan")


def frontier(
    run: str, rows: Iterable[tuple[str, str, str]], plans: Mapping[str, Plan]
) -> Iterator[Plan]:
    """Yield each ready step's plan once, in step-key order."""
    steps = {step for row_run, step, _ in rows if row_run == run}
    for step in sorted(steps):
        yield plans[step]
