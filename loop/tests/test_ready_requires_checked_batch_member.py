"""Retain independent positive transition evidence and reject supplied safety claims."""
import pytest

from rezono_canon import canonical_bytes
from rezono_checker.transition import check_transition_certificate
from round_visibility_cases import A_WITHDRAWN, OPENING, PRIORITIES, RUN, WITHDRAW_A, WITHDRAW_B
from round_visibility_pair import MANIFEST, PROGRAM, pair_evidence
from round_visibility_publication import checked_loop_publication, round_authority, round_candidates


@pytest.mark.xfail(
    strict=True,
    raises=(AssertionError, TypeError),
    reason=(
        "Read decisions/scoped-completeness.md sections 1 and 3 and decisions/loop-certificate-admission.md. "
        "Only the selected members of a valid independently checked current batch certificate enter ready. "
        "A supplied positive result without the complete obligation inventory is not a certificate. Write in "
        "packs/std-loop (ready.dl, fixed_point.dl) and switch the readers of the old ready to unblocked "
        "(loop/typed_recording.py, build/rules/tasks.dl). Waits for test_unblocked_evidence, "
        "test_supplied_verdicts_authorize_nothing and the core round admission: batch.epoch must admit "
        "transition_certificates against transition_authority with the round verifier in the checker and supply "
        "loop_certified_step and loop_certified_member (no core red test yet). Today batch.epoch rejects the "
        "admission keywords with TypeError."
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
    retained = {
        "observed-lanes": OPENING.source_bytes(),
        "lane-inventory": OPENING.inventory_bytes(),
        "definition": canonical_bytes(PROGRAM),
        "round-policy": canonical_bytes({"desired_manifest": MANIFEST, "run": RUN, "cut": OPENING.cut,
                                         "width": 1, "effects": [WITHDRAW_A.plan, WITHDRAW_B.plan],
                                         "priorities": PRIORITIES}),
    }
    authority = [round_authority(retained, run=RUN, cut=OPENING.cut)]
    _, rows, _ = checked_loop_publication(
        tmp_path / "without-certificate", records, retained=retained,
        admission={"transition_certificates": [], "transition_authority": authority},
    )
    assert (rows("safe_alone"), rows("ready")) == (set(), set()), (
        f"An incomplete supplied check authorized a step. safe_alone={rows('safe_alone')}. ready={rows('ready')}"
    )
    submitted = {
        "batch-choice": canonical_bytes({"run": RUN, "cut": OPENING.cut, "members": [WITHDRAW_A.step]}),
        **{
            effect.step: canonical_bytes({"certificate": evidence.certificate, "base": evidence.base,
                                           "variant": evidence.variant})
            for effect, evidence in ((WITHDRAW_A, good), (WITHDRAW_B, other))
        },
    }
    _, rows, _ = checked_loop_publication(
        tmp_path / "with-certificate", records, retained=retained, submitted=submitted,
        admission={"transition_certificates": round_candidates(submitted), "transition_authority": authority},
    )
    assert {row[:2] for row in rows("ready")} == {(RUN, WITHDRAW_A.step)}
    assert all(row[2] for row in rows("ready")), "The selection must retain its proof reason"
