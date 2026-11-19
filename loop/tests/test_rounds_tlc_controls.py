"""The formal round controls and their map from model actions to replay tests."""
from pathlib import Path
import re

import pytest


FORMAL = Path(__file__).resolve().parents[2] / "formal"
# decisions/safe-step-rounds.md section 6 names these controls.
PRESERVED = {"EveryVisiblePrefixValid", "OnlyCertifiedDispatch", "DoneHasCurrentMatchingObservation",
             "AtMostOneSubmitPerNonrepeatableHash", "NoFalseFixedPoint"}
MUST_FAIL = {"RoundsTrustSubmit.cfg": "DoneHasCurrentMatchingObservation",
             "RoundsCombinedOnly.cfg": "EveryVisiblePrefixValid"}
# Actions with an implementation counterpart and the replay test that must exercise them.
REPLAYED = {"Claim": "test_round_claim.py", "SubmitOne": "test_round_submit.py", "Crash": "test_round_submit.py",
            "LoseReply": "test_round_submit.py"}


def _invariants(config):
    text = (FORMAL / config).read_text(encoding="utf-8")
    block = re.search(r"^INVARIANTS?\b(.*?)(?=^[A-Z_]+\b|\Z)", text, re.M | re.S)
    return set(block.group(1).split()) if block else set()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: Read decisions/safe-step-rounds.md section 6 and formal/README.md. Link the Claim row of the Rounds "
        "table in formal/README.md to loop/tests/test_round_claim.py and the SubmitOne, Crash and LoseReply row "
        "to loop/tests/test_round_submit.py. Write in formal/. Waits for test_round_claim_is_durable_and_exclusive "
        "and test_round_submit_follows_the_certified_claim."
    ),
)
def test_rounds_tlc_controls():
    model = (FORMAL / "Rounds.tla").read_text(encoding="utf-8")
    following = model.split("\nNext ==", 1)[1].split("\n\n", 1)[0]
    actions = set(re.findall(r"\\/ (?:\\E [^:]+: )?([A-Z][A-Za-z]+)", following))
    actions |= set(re.findall(r"\\/ ([A-Z][A-Za-z]+)\(", following))
    assert {"Evaluate", "Claim", "SubmitOne", "Crash", "LoseReply", "Correct", "Observe", "CloseSweep",
            "Reconcile", "NextRound", "ConcludeFixedPoint"} <= actions, actions

    assert PRESERVED <= _invariants("Rounds.cfg")
    for config, invariant in MUST_FAIL.items():
        text = (FORMAL / config).read_text(encoding="utf-8")
        assert f"must-fail: {invariant}" in text and _invariants(config) == {invariant}, config

    readme = (FORMAL / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("| Rounds |")]
    for action in actions:
        row = [line for line in rows if f"`{action}`" in line]
        assert len(row) == 1, f"formal/README.md needs exactly one Rounds row for {action}"
        for link in re.findall(r"\]\(([^)]+)\)", row[0]):
            assert (FORMAL / link).resolve().is_file(), link
        if action in REPLAYED:
            assert f"loop/tests/{REPLAYED[action]})" in row[0], f"{action} has no replay test in formal/README.md"
