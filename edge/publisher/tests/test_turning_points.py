"""The publisher's turning points between two neighbouring stops of a sweep (decisions/viewer-slip.md, "Turning
points"), on the hand-written cases of tests/fixtures/turns/cases.py: one stop pair for each cause the decision
lists, a premise that turns and the row on it, and pairs where only an amount moves, which mark nothing."""

import importlib
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = run_path(str(ROOT / "tests" / "fixtures" / "turns" / "cases.py"))
CASES = FIXTURE["CASES"]


class MissingTurningPoints(AssertionError):
    """rezono_publisher.turns.between is not there."""


def between():
    try:
        return importlib.import_module("rezono_publisher.turns").between
    except (ImportError, AttributeError) as error:
        raise MissingTurningPoints(str(error)) from error


def test_turning_points():
    turns = between()
    got = {case: turns(FIXTURE["COLUMNS"], FIXTURE["PROGRAM"], given["before"], given["after"])
           for case, given in sorted(CASES.items())}
    assert got == {case: given["turns"] for case, given in sorted(CASES.items())}
