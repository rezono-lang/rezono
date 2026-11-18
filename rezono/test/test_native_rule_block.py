"""Test native rule reading against the authored language decision."""

import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read native rule blocks and print them through the module form in rezono/src. "
        "Read decisions/language-native-rules.md. Preserve the separate interim rule block."
    ),
)
def test_native_rule_block():
    probe = Path(__file__).with_name("native-rule-block.test.ts")
    result = subprocess.run(
        ["node", str(probe), "--probe"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    mismatch = json.loads(result.stdout)
    assert mismatch is None, mismatch
