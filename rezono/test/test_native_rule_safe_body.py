"""Check one native rule acceptance contract against supplied signatures."""

import json
from pathlib import Path
import subprocess

import pytest


class NativeRuleMismatch(AssertionError):
    """The typed checker is missing or differs from the authored cases."""


def test_native_rule_safe_body():
    probe = Path(__file__).with_name("native-rule-safe-body.mts")
    result = subprocess.run(
        ["node", str(probe)], check=True, capture_output=True, text=True, encoding="utf-8",
    )
    differences = json.loads(result.stdout)
    if not isinstance(differences, list):
        raise TypeError("The native rule probe must report a list of differences")
    if differences:
        raise NativeRuleMismatch(json.dumps(differences, indent=2))
