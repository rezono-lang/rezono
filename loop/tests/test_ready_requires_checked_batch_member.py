"""Retain independent positive transition evidence and reject supplied safety claims."""
import pytest

from rezono_checker.transition import check_transition_certificate
from round_visibility_cases import A_WITHDRAWN, OPENING, RUN, WITHDRAW_A, WITHDRAW_B
from round_visibility_pair import pair_evidence
from round_visibility_publication import checked_loop_publication
from round_visibility_rounds import singleton_rounds


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/loop-certificate-admission.md: Read it and decisions/admission-transport.md sections 6 to 8. "
        "Only the members of an admitted verified round for the current run and cut enter ready: "
        "ready(run, step, reason) needs current_verified_round(round, run, cut, batch) and "
        "verified_round_member(round, step), and keeps a proof reason. Of the two claims in "
        "round_visibility_rounds only withdraw-a's is admitted. A supplied positive "
        "result is not a certificate. Write in packs/std-loop (ready.dl, fixed_point.dl) and switch the readers "
        "of the old ready to unblocked (loop/typed_recording.py, build/rules/tasks.dl, and refresh the std-loop "
        "pin in build/pack.yaml and the table in compiler/rezono_compiler/standard_packs.py). The same change turns "
        "loop/tests/test_overlapping_withdrawals_break_availability.py::"
        "test_overlapping_withdrawals_break_availability green: remove both marks in the same PR. Today ready.dl "
        "still derives ready from eligible without a verified round (AssertionError). "
        "Note: switching ready.dl to current_verified_round and verified_round_member (with fixed_point.dl, "
        "loop/typed_recording.py, and build/rules/tasks.dl switched to unblocked) makes this test and "
        "test_overlapping_withdrawals_break_availability pass, but breaks the green test "
        "loop/tests/test_quiet_round.py::test_quiet_round_rules because it checks rows['ready'] instead of "
        "rows['unblocked'] without a verified round. A planner PR must switch test_quiet_round_rules to "
        "unblocked (and packs/std-loop/candidate/ also needs ready and fixed_point updated)."
    ),
)
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
