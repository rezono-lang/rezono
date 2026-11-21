"""Disjointness invariants for loop.build_decision_work.read_decision_work."""

from __future__ import annotations

import pytest

from loop.build_decision_work import read_decision_work

GREEN_MANIFEST = {
    "checks": [
        {"name": "rezono:proofs", "status": "green"},
        {"name": "rezono:schema", "status": "green"},
    ]
}


def _rows(*keys: tuple[str, ...]) -> list[dict[str, list[str]]]:
    return [{"key": list(key)} for key in keys]


def _empty_rows() -> dict[str, list[dict[str, list[str]]]]:
    return {
        "build_decision_open": [],
        "build_decision_open_test": [],
        "build_decision_untested": [],
        "build_decision_done": [],
    }


@pytest.mark.parametrize("relation", ("build_decision_open", "build_decision_untested", "build_decision_done"))
def test_read_decision_work_rejects_headless_decision_in_classified_status_relations(relation: str) -> None:
    """Headless decisions must stay exclusively unknown and never overlap open, untested or done."""
    rows = _empty_rows()
    rows[relation] = _rows(("current", "headless-one"))
    if relation == "build_decision_open":
        rows["build_decision_open_test"] = _rows(("current", "headless-one", "loop/tests/test_work.py--test_case"))

    with pytest.raises(ValueError, match="headless-one"):
        read_decision_work(
            run="current",
            manifest=GREEN_MANIFEST,
            rows=rows,
            headless_decisions=("decisions/headless-one.md",),
            known_decisions=("headless-one",),
        )
