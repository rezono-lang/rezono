"""The checker's own reading of turning points (decisions/viewer-slip.md, "Turning points"): for two neighbouring
stops it accepts exactly the hand-written list of tests/fixtures/turns/cases.py, and refuses a list with a row too
many, a row too few, or another cause. It imports nothing of the publisher."""

import copy
import importlib
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = run_path(str(ROOT / "tests" / "fixtures" / "turns" / "cases.py"))
CASES = FIXTURE["CASES"]


class MissingTurnCheck(AssertionError):
    """rezono_checker.turns.check is not there."""


def check():
    try:
        return importlib.import_module("rezono_checker.turns").check
    except (ImportError, AttributeError) as error:
        raise MissingTurnCheck(str(error)) from error


@pytest.mark.xfail(
    strict=True,
    raises=(MissingTurnCheck, AssertionError),
    reason=(
        "M3: decisions/viewer-slip.md: Write checker/rezono_checker/turns.py with check(columns, program, before, after, listed) -> list of "
        "problems: it derives the turning points between two stops itself, as decisions/viewer-slip.md, section "
        "Turning points, defines them, and names every row listed too many or too few and every other cause. "
        "It shares no code with the publisher. Inputs as in tests/fixtures/turns/cases.py."
    ),
)
def test_turning_points_checked():
    columns, program = FIXTURE["COLUMNS"], FIXTURE["PROGRAM"]
    verify = check()
    for case, given in sorted(CASES.items()):
        before, after, turns = given["before"], given["after"], given["turns"]
        assert verify(columns, program, before, after, turns) == [], case
        extra = {"relation": "zzz", "key": '["x9"]', "causes": ["presence"]}
        assert verify(columns, program, before, after, [*turns, extra]), case
        if turns:
            assert verify(columns, program, before, after, turns[1:]), case
            other = copy.deepcopy(turns)
            other[0]["causes"] = ["rule"] if other[0]["causes"] != ["rule"] else ["presence"]
            assert verify(columns, program, before, after, other), case
