"""A retained round context and submitted round claims for the opening lane readback.

The certificates are the hand-authored pair fixtures of round_visibility_pair. The width is one. withdraw-a
and withdraw-b are each safe alone, and the pack priority puts withdraw-a first, so the round verifier of
decisions/admission-transport.md section 7 admits the claim for withdraw-a and refuses the claim for
withdraw-b: nothing refutes withdraw-a, which precedes it.
"""
from rezono_canon import canonical_bytes
from round_visibility_cases import A_WITHDRAWN, OPENING, PRIORITIES, RUN, WITHDRAW_A, WITHDRAW_B
from round_visibility_pair import INVARIANTS, MANIFEST, PROGRAM, pair_evidence
from round_visibility_publication import observation_reference, round_claim, round_context

TARGETS = {WITHDRAW_A: A_WITHDRAWN.state, WITHDRAW_B: ("old", "offline")}


def singleton_rounds():
    """Return (retained, submitted, context, index) for one width-one round at the opening cut."""
    pairs = {effect: pair_evidence(OPENING, (effect,), target) for effect, target in TARGETS.items()}
    retained = {
        "observed-lanes": OPENING.source_bytes(),
        "lane-inventory": OPENING.inventory_bytes(),
        "definition": canonical_bytes(PROGRAM),
        "base": canonical_bytes(pairs[WITHDRAW_A].base),
        "round-domain": canonical_bytes({"width": 1, "steps": [
            {"step": effect.step, "priority": PRIORITIES[effect.step], "effects": [effect.plan_hash]}
            for effect in TARGETS
        ]}),
    }
    context = {"rounds": [round_context(
        retained, run=RUN, cut=pairs[WITHDRAW_A].context["cut"], manifest=MANIFEST, invariants=INVARIANTS,
        program="definition", observations={f"read-{OPENING.cut}": "observed-lanes"}, base="base",
        domain="round-domain",
    )]}
    submitted = {}
    for effect, pair in pairs.items():
        submitted[f"certificate-{effect.step}"] = canonical_bytes(pair.certificate)
        submitted[f"variant-{effect.step}"] = canonical_bytes(pair.variant)
        submitted[f"claim-{effect.step}"] = canonical_bytes(round_claim(
            submitted, run=RUN, cut=OPENING.cut, batch=f"batch-{effect.step}", members=[effect.step],
            subsets=[([effect.step], f"variant-{effect.step}", f"certificate-{effect.step}")],
        ))
    claims = [f"claim-{effect.step}" for effect in TARGETS]
    index = {"rounds": [observation_reference("submitted", name, submitted[name]) for name in claims]}
    return retained, submitted, context, index
