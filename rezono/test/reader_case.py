"""Run a reader case through the same module writer as the native Node suite."""

import json
from pathlib import Path
import subprocess


def assert_reader_case(case):
    directory = Path(__file__).parent / "reader_cases"
    result = subprocess.run(
        ["node", str(directory / "check.mjs"), str(directory / f"{case}.json")],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    mismatch = json.loads(result.stdout)
    assert mismatch is None, mismatch
