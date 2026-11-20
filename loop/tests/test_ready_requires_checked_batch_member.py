"""Retain independent positive transition evidence and reject supplied safety claims."""
import pytest

from rezono_checker.transition import check_transition_certificate
from round_visibility_cases import A_WITHDRAWN, OPENING, RUN, WITHDRAW_A, WITHDRAW_B
from round_visibility_pair import pair_evidence
from round_visibility_publication import checked_loop_publication
from round_visibility_rounds import singleton_rounds


def test_ready_requires_checked_batch_member(tmp_path):
    good = pair_evidence(OPENING, (WITHDRAW_A,), A_WITHDRAWN.state)
    assert check_transition_certificate(*good) == {"valid": True, "findings": []}
    omitted = pair_evidence(OPENING, (WITHDRAW_A,), A_WITHDRAWN.state)
    del omitted.certificate["invariants"]["missing_lane"]
    assert check_transition_certificate(*omitted)["findings"] == [{"reason": "invariant_inventory_mismatch"}]
    other = pair_evidence(OPENING, (WITHDRAW_B,), ("old", "offline"))
    assert check_transition_certificate(*other)["valid"]

    records = {
        "loop_active_run": [{"id": RUN}],
        "loop_sweep_receipt": [{"id": OPENING.cut, "run": RUN, "event_time": OPENING.event_time}],
        "loop_step": [{"id": effect.step} for effect in (WITHDRAW_A, WITHDRAW_B)],
        "loop_step_safety_check": [{
            "id": "availability-only", "run": RUN, "step": WITHDRAW_A.step, "cut": OPENING.cut,
            "obligation": "at-least-one-lane-serving", "verdict": "proved", "reason": "submitted-positive",
        }],
    }
    retained, submitted, context, index = singleton_rounds()
    _, rows, _ = checked_loop_publication(
        tmp_path / "without-certificate", records, retained=retained, context=context, index={},
    )
    # safe_alone under a supplied check is test_supplied_verdicts_authorize_nothing's; this test owns ready.
    assert rows("ready") == set(), f"An incomplete supplied check made a step ready: {rows('ready')}"
    _, rows, _ = checked_loop_publication(
        tmp_path / "with-certificate", records, retained=retained, submitted=submitted, context=context, index=index,
    )
    assert {row[:2] for row in rows("ready")} == {(RUN, WITHDRAW_A.step)}
    assert all(row[2] for row in rows("ready")), "The selection must retain its proof reason"
