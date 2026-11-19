"""Replay the Claim action of formal/Rounds.tla against a durable conditional write."""
from importlib.util import find_spec

import pytest

from rezono_publisher import store


PLAN, OTHER = "c" * 64, "d" * 64


def test_round_claim_is_durable_and_exclusive(tmp_path):
    assert find_spec("loop.round_claim") is not None, "The durable attempt claim is not wired"
    from loop.round_claim import claim_attempt

    archive = store.FileStore(tmp_path / "archive")
    first = claim_attempt(archive, plan_hash=PLAN, run="run-1", cut="cut-1", worker="worker-1")
    assert first == {"plan_hash": PLAN, "run": "run-1", "cut": "cut-1", "worker": "worker-1"}

    # Rounds.tla Claim requires claims[m] = 0: a second worker gets nothing.
    assert claim_attempt(archive, plan_hash=PLAN, run="run-1", cut="cut-1", worker="worker-2") is None
    # A retry by the holder at the same pin coalesces with its own claim.
    assert claim_attempt(archive, plan_hash=PLAN, run="run-1", cut="cut-1", worker="worker-1") == first

    # The claim survives a restart and is retained across cuts and runs: one hash, one attempt.
    reopened = store.FileStore(tmp_path / "archive")
    for worker in ("worker-1", "worker-2"):
        assert claim_attempt(reopened, plan_hash=PLAN, run="run-2", cut="cut-2", worker=worker) is None, worker

    # A different plan hash is claimed independently.
    assert claim_attempt(reopened, plan_hash=OTHER, run="run-2", cut="cut-2", worker="worker-2") == {
        "plan_hash": OTHER, "run": "run-2", "cut": "cut-2", "worker": "worker-2",
    }

    for bad in ({"plan_hash": "C" * 64}, {"plan_hash": "c" * 63}, {"worker": ""}, {"cut": ""}):
        arguments = {"plan_hash": "e" * 64, "run": "run-2", "cut": "cut-2", "worker": "worker-1", **bad}
        with pytest.raises(ValueError):
            claim_attempt(reopened, **arguments)
