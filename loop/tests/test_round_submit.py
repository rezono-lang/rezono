"""Replay the SubmitOne, Crash and LoseReply guards of formal/Rounds.tla."""
from copy import deepcopy
from importlib.util import find_spec

import pytest


PIN = {"run": "run-1", "cut": "cut-1"}
STATE = {
    "pin": PIN,
    "chosen": {"pin": PIN, "members": ["protect", "expose"]},
    "pending": ["protect", "expose"],
    "claims": {"protect": "worker-1", "expose": "worker-2"},
    "stopped": [],
    "lost": [],
    "submitted": [],
    "done": [],
}


def test_round_submit_follows_the_certified_claim():
    assert find_spec("loop.round_submit") is not None, "The submit guard is not wired"
    from loop.round_submit import record_submit, submit_refusal

    assert submit_refusal(STATE, worker="worker-1", member="protect") is None
    before = deepcopy(STATE)
    after = record_submit(STATE, worker="worker-1", member="protect")
    assert STATE == before, "record_submit must not change its input"
    assert after["submitted"] == [{"member": "protect", "worker": "worker-1", "pin": PIN, "certificate": PIN}]
    # Submission is not completion: only matching readback at the current pin adds to done.
    assert after["done"] == []

    def changed(**fields):
        return {**deepcopy(STATE), **fields}

    # Each case breaks exactly one guard of SubmitOne.
    cases = [
        (changed(pin={"run": "run-1", "cut": "cut-2"}), "worker-1", "protect", "stale_certificate"),
        (changed(pin={"run": "run-2", "cut": "cut-1"}), "worker-1", "protect", "stale_certificate"),
        (changed(pending=["expose"]), "worker-1", "protect", "not_pending"),
        (STATE, "worker-2", "protect", "not_claimant"),
        (changed(claims={"expose": "worker-2"}), "worker-1", "protect", "not_claimant"),
        (changed(stopped=["worker-1"]), "worker-1", "protect", "worker_stopped"),
        (after, "worker-1", "protect", "already_submitted"),
        (changed(submitted=after["submitted"], lost=["protect"]), "worker-1", "protect", "already_submitted"),
    ]
    for state, worker, member, refusal in cases:
        assert submit_refusal(state, worker=worker, member=member) == refusal, (worker, member, refusal)

    # After a crash the claimed member stays unresolved: neither the stopped holder nor another worker submits it.
    crashed = changed(stopped=["worker-1"])
    assert submit_refusal(crashed, worker="worker-1", member="protect") == "worker_stopped"
    assert submit_refusal(crashed, worker="worker-2", member="protect") == "not_claimant"
    assert submit_refusal(crashed, worker="worker-2", member="expose") is None


def test_round_submit_refuses_an_unknown_stopped_or_submitted_set():
    from loop.round_submit import record_submit, submit_refusal

    # A missing set is unknown, not empty: the guard cannot be checked, so submission is refused.
    no_stopped = {key: value for key, value in deepcopy(STATE).items() if key != "stopped"}
    no_submitted = {key: value for key, value in deepcopy(STATE).items() if key != "submitted"}
    neither = {key: value for key, value in deepcopy(STATE).items() if key not in ("stopped", "submitted")}
    assert submit_refusal(no_stopped, worker="worker-1", member="protect") == "stopped_unknown"
    assert submit_refusal(no_submitted, worker="worker-1", member="protect") == "submitted_unknown"
    assert submit_refusal(neither, worker="worker-1", member="protect") == "stopped_unknown"
    with pytest.raises(ValueError, match="submitted_unknown"):
        record_submit(no_submitted, worker="worker-1", member="protect")
