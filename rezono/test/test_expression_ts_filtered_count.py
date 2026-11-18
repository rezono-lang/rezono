"""Run the shared filtered group through the native TypeScript check boundary."""

import json
from pathlib import Path
import subprocess

import pytest


class MissingFilteredCountTyping(AssertionError):
    """The incumbent checker rejects the entire checked fixed-key filter."""


@pytest.mark.xfail(strict=True, raises=MissingFilteredCountTyping,
                   reason="Check fixed-key filtered groups in rezono/src/native-rule-check.ts. "
                          "Read decisions/language-expression-semantics.md. Waits for test_expression_ts_negated_call "
                          "while it owns the same checker.")
def test_expression_ts_filtered_count():
    probe = Path(__file__).with_name("expression-filtered-count.mts")
    result = subprocess.run(["node", str(probe)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    mismatch = json.loads(result.stdout)
    if mismatch == "filtered aggregate rejected":
        raise MissingFilteredCountTyping(mismatch)
    assert mismatch is None, mismatch
