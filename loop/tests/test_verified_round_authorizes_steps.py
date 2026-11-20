"""safe_alone and the certified and selected batch follow only from an admitted verified round.

The expectation comes from decisions/admission-transport.md section 8: a pack that needs a step that is
safe on its own reads a verified round whose batch has that single member, and a pack that needs the
certified batch reads verified_round and its members. The round evidence is the hand-authored fixture of
round_visibility_rounds; no supplied verdict is present, so only admission can authorize.
"""
import pytest

from rezono_canon import canonical_bytes
from round_visibility_cases import A_WITHDRAWN, OPENING, RUN, WITHDRAW_A, WITHDRAW_B
from round_visibility_publication import checked_loop_publication, observation_reference, round_claim
from round_visibility_rounds import singleton_rounds

AUTHORIZED = ("safe_alone", "loop_certified_batch", "loop_selected_batch")


def _records(*readbacks):
    return {
        "loop_active_run": [{"id": RUN}],
        "loop_sweep_receipt": [{"id": readback.cut, "run": RUN, "event_time": readback.event_time}
                               for readback in readbacks],
        "loop_step": [{"id": effect.step} for effect in (WITHDRAW_A, WITHDRAW_B)],
    }


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

    # Counterexample: a second admitted claim of the same run and cut that names another batch leaves the
    # choice undecided, so neither batch is selected.
    relabelled = dict(submitted)
    relabelled["claim-relabelled"] = canonical_bytes(round_claim(
        relabelled, run=RUN, cut=OPENING.cut, batch="batch-relabelled", members=[WITHDRAW_A.step],
        subsets=[([WITHDRAW_A.step], [WITHDRAW_A.plan_hash], f"variant-{WITHDRAW_A.step}",
                  f"certificate-{WITHDRAW_A.step}")],
    ))
    both = {"rounds": [*index["rounds"],
                       observation_reference("submitted", "claim-relabelled", relabelled["claim-relabelled"])]}
    _, rows, _ = checked_loop_publication(
        tmp_path / "relabelled", _records(OPENING), retained=retained, submitted=relabelled, context=context,
        index=both,
    )
    assert {row[0] for row in rows("loop_certified_batch")} == {f"batch-{WITHDRAW_A.step}", "batch-relabelled"}
    assert rows("loop_selected_batch") == set(), f"Two admitted rounds selected: {rows('loop_selected_batch')}"
