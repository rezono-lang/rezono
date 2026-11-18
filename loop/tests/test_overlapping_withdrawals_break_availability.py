"""Require the round proof to account for intermediate adapter boundaries."""
import json

import pytest

from rezono_canon import canonical_bytes
from rezono_checker.transition import check_transition_certificate
from round_visibility_cases import (
    ACTIVATE_A, A_RESTORED, A_WITHDRAWN, ALL_STATES, EFFECTS, Effect, FINISHED_ONLY, INITIAL,
    LANES, OPENING, ROUNDS, RUN, SOLO_A, SOLO_B, VIOLATION, WITHDRAW_A, WITHDRAW_B, serving, visible_boundaries,
)
from round_visibility_pair import MANIFEST, PROGRAM, pair_evidence
from round_visibility_publication import checked_loop_publication


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/scoped-completeness.md sections 3 and 4. Reconstruct all nine visible "
        "boundaries from the retained effect declarations. Refuse overlapping withdrawals even when "
        "every submitted pair checks and the violating boundary was left out. Preserve observed "
        "old rows and residual effects. Write in the Loop round admission path."
    ),
)
def test_overlapping_withdrawals_break_availability(tmp_path):
    states = visible_boundaries(INITIAL, EFFECTS)
    assert set(states) == ALL_STATES and sum(map(len, states.values())) == 12
    assert set(visible_boundaries(INITIAL, EFFECTS[:2])) == SOLO_A
    assert set(visible_boundaries(INITIAL, EFFECTS[2:])) == SOLO_B
    assert all(serving(state) for state in SOLO_A | SOLO_B | FINISHED_ONLY)
    assert {state for state in states if not serving(state)} == {VIOLATION}

    # The ordinary pair checker accepts every safe supplied pair. An exact list of
    # completed subsets, or valid proofs for eight individually safe states, misses the outage.
    submitted = {}
    for number, target in enumerate(sorted(ALL_STATES - {VIOLATION})):
        net_effects = tuple(
            Effect(f"pair-{lane}", lane, old, new)
            for lane, old, new in zip(LANES, INITIAL, target, strict=True) if old != new
        )
        pair = pair_evidence(OPENING, net_effects, target)
        assert check_transition_certificate(*pair)["valid"]
        submitted[f"pair-{number}"] = canonical_bytes({
            "state": target, "certificate": pair.certificate, "base": pair.base, "variant": pair.variant,
        })
    assert len(submitted) == 8

    overlap = pair_evidence(OPENING, (WITHDRAW_A, WITHDRAW_B), VIOLATION)
    assert not check_transition_certificate(*overlap)["valid"]
    assert states[A_WITHDRAWN.state][WITHDRAW_B] == VIOLATION
    assert states[A_WITHDRAWN.state][ACTIVATE_A] == A_RESTORED.state
    for current, following in zip(ROUNDS[:-1], ROUNDS[1:], strict=True):
        readback = current.readback
        (chosen,) = current.selected
        assert set(states[readback.state]) == set(current.candidates)
        assert states[readback.state][chosen] == following.readback.state
        assert check_transition_certificate(*pair_evidence(
            readback, (chosen,), following.readback.state,
        ))["valid"]
        observed = json.loads(following.readback.source_bytes())
        assert observed["plan_hash"] == chosen.plan_hash
        assert observed["cut"] == following.readback.cut
    unobserved = pair_evidence(OPENING, (ACTIVATE_A,), A_RESTORED.state)
    assert check_transition_certificate(*unobserved)["findings"] == [{"reason": "delta_old_row_missing"}]

    members = ("replace-a", "replace-b")
    retained = {
        "definition": canonical_bytes(PROGRAM),
        "observed-lanes": OPENING.source_bytes(),
        "lane-inventory": OPENING.inventory_bytes(),
        "effect-declarations": canonical_bytes({
            "desired_manifest": MANIFEST, "run": RUN, "cut": OPENING.cut,
            "steps": [
                {"step": member, "ordered_effects": [effect.plan for effect in EFFECTS[offset:offset + 2]]}
                for member, offset in zip(members, (0, 2), strict=True)
            ],
        }),
    }
    submitted["batch-choice"] = canonical_bytes({"run": RUN, "cut": OPENING.cut, "members": members})
    records = {
        "loop_active_run": [{"id": RUN}],
        "loop_sweep_receipt": [{"id": OPENING.cut, "run": RUN, "event_time": OPENING.event_time}],
        "loop_step": [{"id": step} for step in members],
        "loop_step_safety_check": [
            {"id": step, "run": RUN, "step": step, "cut": OPENING.cut,
             "obligation": "availability", "verdict": "proved", "reason": "represented-boundaries"}
            for step in members
        ],
    }
    _, rows, _ = checked_loop_publication(tmp_path, records, retained=retained, submitted=submitted)
    assert not rows("ready"), f"A batch with an omitted unsafe intermediate boundary was published ready: {rows('ready')}"
