"""Choose the suites to run while the pack selection is compared with the Python selection."""

from collections.abc import Set
from typing import Any


def _suites(name: str, selection: object, universe: frozenset[str]) -> frozenset[str]:
    """Return a selection as a frozen set, or raise when it names an unknown suite."""
    if not isinstance(selection, Set) or not all(isinstance(suite, str) for suite in selection):
        raise ValueError(f"malformed {name} selection: {selection!r}")
    unknown = sorted(set(selection) - universe)
    if unknown:
        raise ValueError(f"{name} selection names unknown suites: {unknown}")
    return frozenset(selection)


def transition_choice(
    *,
    run: str,
    pack: Set[str] | None,
    python: Set[str],
    universe: Set[str],
) -> dict[str, Any]:
    """Keep the Python result, record a disagreement with both sides, and run every suite when the pack is unverified.

    ``pack`` is ``None`` when capturing or verifying the pack result failed; that requests full checks.
    """
    if not isinstance(run, str) or not run:
        raise ValueError(f"malformed run: {run!r}")
    known = _suites("universe", universe, frozenset(universe) if isinstance(universe, Set) else frozenset())
    chosen = _suites("python", python, known)
    if pack is None:
        return {"run": run, "use": sorted(known), "source": "full", "disagreement": None}
    proposed = _suites("pack", pack, known)
    if proposed == chosen:
        return {"run": run, "use": sorted(chosen), "source": "agreed", "disagreement": None}
    return {
        "run": run,
        "use": sorted(chosen),
        "source": "python",
        "disagreement": {
            "run": run,
            "only_pack": sorted(proposed - chosen),
            "only_python": sorted(chosen - proposed),
        },
    }
