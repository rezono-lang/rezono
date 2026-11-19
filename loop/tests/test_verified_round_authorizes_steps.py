"""safe_alone and the certified and selected batch follow only from an admitted verified round.

The expectation comes from decisions/admission-transport.md section 8: a pack that needs a step that is
safe on its own reads a verified round whose batch has that single member, and a pack that needs the
certified batch reads verified_round and its members. The round evidence is the hand-authored fixture of
round_visibility_rounds; no supplied verdict is present, so only admission can authorize.
"""
import pytest

from round_visibility_cases import A_WITHDRAWN, OPENING, RUN, WITHDRAW_A, WITHDRAW_B
from round_visibility_publication import checked_loop_publication
from round_visibility_rounds import singleton_rounds

AUTHORIZED = ("safe_alone", "loop_certified_batch", "loop_selected_batch")


def _records(*readbacks):
    return {
        "loop_active_run": [{"id": RUN}],
        "loop_sweep_receipt": [{"id": readback.cut, "run": RUN, "event_time": readback.event_time}
                               for readback in readbacks],
        "loop_step": [{"id": effect.step} for effect in (WITHDRAW_A, WITHDRAW_B)],
    }


@pytest.mark.xfail(
    strict=True,
    raises=(AssertionError, ImportError, TypeError),
    reason=(
        "Read decisions/admission-transport.md sections 6 and 8 and decisions/loop-certificate-admission.md "
        "section 2. Declare verified_round and verified_round_member in std-loop with the reserved signatures "
        "and no clause. Derive safe_alone(run, step, cut) from a verified round of the current run and cut "
        "whose batch has exactly that one member, and loop_certified_batch and loop_selected_batch from a "
        "verified round of the current run and cut, with the round's batch as the batch column. Keep the "
        "supplied-verdict derivations for now; test_supplied_verdicts_authorize_nothing removes them. Write in "
        "packs/std-loop (step_safety.dl, batch_selection.dl and their schema). Waits for "
        "edge/publisher/tests/test_round_evidence_batch.py--test_batch_admits_certified_rounds_before_the_rules, "
        "edge/publisher/tests/test_completeness_publish.py--"
        "test_publisher_admits_receipts_only_with_a_trusted_context (the checker admits again on publish) and "
        "compiler/tests/test_protected_admission_relations.py--test_admission_relations_are_protected_inputs. "
        "Today rezono_checker.evidence is missing (ImportError)."
    ),
)
def test_verified_round_authorizes_steps(tmp_path):
    retained, submitted, context, index = singleton_rounds()
    _, rows, _ = checked_loop_publication(
        tmp_path / "admitted", _records(OPENING), retained=retained, submitted=submitted, context=context,
        index=index,
    )
    assert rows("safe_alone") == {(RUN, WITHDRAW_A.step, OPENING.cut)}
    assert rows("loop_selected_batch") == {(f"batch-{WITHDRAW_A.step}",)}
    assert {row[0] for row in rows("loop_certified_batch")} == {f"batch-{WITHDRAW_A.step}"}

    # Counterexample: the same claims without the trusted round context are not admitted.
    _, rows, _ = checked_loop_publication(
        tmp_path / "untrusted", _records(OPENING), retained=retained, submitted=submitted, context={},
        index=index,
    )
    authorized = {relation: rows(relation) for relation in AUTHORIZED}
    assert authorized == {relation: set() for relation in AUTHORIZED}, f"Untrusted claims authorized: {authorized}"

    # Counterexample: an admitted round for an earlier cut authorizes nothing at the current cut.
    _, rows, _ = checked_loop_publication(
        tmp_path / "stale", _records(OPENING, A_WITHDRAWN), retained=retained, submitted=submitted,
        context=context, index=index,
    )
    authorized = {relation: rows(relation) for relation in AUTHORIZED}
    assert authorized == {relation: set() for relation in AUTHORIZED}, f"A stale round authorized: {authorized}"
