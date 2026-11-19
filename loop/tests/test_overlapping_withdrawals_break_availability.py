"""Require the round proof to account for intermediate adapter boundaries."""
import json

import pytest

from rezono_canon import canonical_bytes, canonical_sha256
from rezono_checker.transition import check_transition_certificate
from round_visibility_cases import (
    ACTIVATE_A, A_RESTORED, A_WITHDRAWN, ALL_STATES, EFFECTS, Effect, FINISHED_ONLY, INITIAL,
    LANES, OPENING, ROUNDS, RUN, SOLO_A, SOLO_B, VIOLATION, WITHDRAW_A, WITHDRAW_B, serving, visible_boundaries,
)
from round_visibility_pair import INVARIANTS, MANIFEST, PROGRAM, pair_evidence
from round_visibility_publication import (
    checked_loop_publication, observation_reference, round_claim, round_context,
)


@pytest.mark.xfail(
    strict=True,
    raises=(AssertionError, ImportError, TypeError),
    reason=(
        "M2: decisions/loop-certificate-admission.md: Read it and decisions/admission-transport.md sections 3 and 7. "
        "The round verifier rebuilds the eight visible boundaries of the two ordered steps from the plan hashes "
        "in the retained domain and refuses the claim, because the violating boundary has no certificate even "
        "though every submitted pair checks. So no verified_round row is admitted and nothing is ready. "
        "Preserve observed old rows and residual effects. Waits for test_ready_requires_checked_batch_member "
        "and for a core red test in checker/tests that has the round verifier rebuild the visible boundaries "
        "of a step with ordered effects (not yet written; the checker is core's). Write in packs/std-loop only "
        "if the ready rules still need it. Today admission already refuses the claim (round_boundary_missing "
        "for withdraw-a with withdraw-b), but the supplied availability verdicts still make both steps ready "
        "(AssertionError)."
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
    progress = {"old": 0, "offline": 1, "new": 2}
    members = ("replace-a", "replace-b")
    pairs = []
    submitted = {}
    for number, target in enumerate(sorted(ALL_STATES - {VIOLATION})):
        net_effects = tuple(
            Effect(f"pair-{lane}", lane, old, new)
            for lane, old, new in zip(LANES, INITIAL, target, strict=True) if old != new
        )
        # A subset of ordered steps names the steps it advances and the effects applied at that boundary, a
        # prefix of each step's effects in domain order, and its certificate binds the digest of their plan
        # hashes in order (decisions/admission-transport.md section 7).
        advanced = [(member, EFFECTS[offset:offset + progress[phase]])
                    for member, offset, phase in zip(members, (0, 2), target, strict=True) if progress[phase]]
        applied = [effect for _, prefix in advanced for effect in prefix]
        pair = pair_evidence(OPENING, net_effects, target)
        pair.certificate["effect"] = canonical_sha256([effect.plan_hash for effect in applied])
        assert check_transition_certificate(*pair)["valid"]
        submitted[f"variant-{number}"] = canonical_bytes(pair.variant)
        submitted[f"certificate-{number}"] = canonical_bytes(pair.certificate)
        # The initial state applies no effect and is no visible boundary, so the claim does not name it.
        if advanced:
            pairs.append(([member for member, _ in advanced], [effect.plan_hash for effect in applied],
                          f"variant-{number}", f"certificate-{number}"))
    assert len(pairs) == 7

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

    retained = {
        "definition": canonical_bytes(PROGRAM),
        "observed-lanes": OPENING.source_bytes(),
        "lane-inventory": OPENING.inventory_bytes(),
        "base": canonical_bytes(overlap.base),
        "round-domain": canonical_bytes({"width": 2, "steps": [
            {"step": member, "priority": priority, "effects": [effect.plan_hash for effect in EFFECTS[offset:offset + 2]]}
            for member, priority, offset in zip(members, (0, 1), (0, 2), strict=True)
        ]}),
    }
    submitted["claim"] = canonical_bytes(round_claim(
        submitted, run=RUN, cut=OPENING.cut, batch="replace-both", members=members, subsets=pairs,
    ))
    context = {"rounds": [round_context(
        retained, run=RUN, cut=overlap.context["cut"], manifest=MANIFEST, invariants=INVARIANTS,
        program="definition", observations={f"read-{OPENING.cut}": "observed-lanes"}, base="base",
        domain="round-domain",
    )]}
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
    _, rows, _ = checked_loop_publication(
        tmp_path, records, retained=retained, submitted=submitted, context=context,
        index={"rounds": [observation_reference("submitted", "claim", submitted["claim"])]},
    )
    assert not rows("ready"), f"A batch with an omitted unsafe intermediate boundary was published ready: {rows('ready')}"
