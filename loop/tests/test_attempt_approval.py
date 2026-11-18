"""Bind a nonrepeatable attempt to its exact approved plan."""

import pytest

from wire_fixtures import entry


def test_attempt_approval(monkeypatch):
    claimable = entry(monkeypatch, "attempt_approval", "claimable")
    digest = "ba" * 32
    assert claimable(plan_hash=digest, approved_hash=digest, state="planned")
    for approval, state in [(None, "planned"), ("cd" * 32, "planned"), (digest, "unknown"),
                            (digest, "applying"), (digest, "cleaned"), (digest, "failed")]:
        assert not claimable(plan_hash=digest, approved_hash=approval, state=state)
