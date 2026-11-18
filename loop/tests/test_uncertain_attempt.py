"""Reconcile a consumed or uncertain nonrepeatable effect through status only."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement loop/uncertain_attempt.py. Reconcile a consumed or uncertain nonrepeatable effect through status only.")
def test_uncertain_attempt(monkeypatch):
    next_operation = entry(monkeypatch, "uncertain_attempt", "next_operation")
    digest = "bc" * 32
    assert next_operation(digest, {"idempotency_key": digest, "state": "unknown"}) == "status"
    assert next_operation(digest, {"idempotency_key": digest, "state": "applying"}) == "status"
    assert next_operation(digest, {"idempotency_key": digest, "state": "applied"}) is None
    with pytest.raises(ValueError):
        next_operation(digest, {"idempotency_key": "de" * 32, "state": "unknown"})
