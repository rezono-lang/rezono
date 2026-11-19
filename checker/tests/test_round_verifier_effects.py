"""A step with several effects in a fixed order, from decisions/admission-transport.md section 7.

Each prefix of a step's effects is a visible boundary: the base, the state after the first effect, and the
state after both. The round verifier rebuilds those boundaries from the retained domain and needs one valid
certificate from the base for each nonempty prefix. A certificate binds the SHA-256 of the ordered plan hashes
it applies. The intermediate state, with no tail at all, is written out by hand.
"""

import pytest
from rezono_canon import canonical_sha256
from test_round_verifier import (
    CUT,
    INVARIANTS,
    MANIFEST,
    OBSERVATIONS,
    PROGRAM,
    RUN,
    Archive,
    certificate,
)
from test_transition_certificate import DELTA, NEW, OLD, row_ref, snapshot

STEP = "replace-link-a"
PLANS = ["plan-remove-tail", "plan-add-tail"]
DOMAIN = {"width": 1, "steps": [{"step": STEP, "priority": 1, "effects": PLANS}]}


def detached():
    """The state after the first effect: the old tail removed, the new one not yet added."""
    return {"id": "detached", "witnesses": [], "rows": {
        "link__tail": [], "outgoing": [], "allowed": [("item-a",), ("item-b",)], "labelled": [("link-a",)],
        "blocked_tail": [], "unlabelled_link": []}}


def boundaries():
    base, middle, final = snapshot("base", OLD), detached(), snapshot("variant", NEW)
    first = certificate(STEP, base, middle, effect=canonical_sha256(PLANS[:1]), delta=[DELTA[0]])
    both = certificate(STEP, base, final, effect=canonical_sha256(PLANS))
    return base, [(PLANS[:1], first, middle), (PLANS, both, final)]


def fixture(prefixes):
    archive = Archive()
    base, _ = boundaries()
    context = {
        "run": RUN, "cut": CUT, "manifest": MANIFEST, "definition_sha256": canonical_sha256(PROGRAM),
        "program": archive.pin("program.json", PROGRAM), "invariants": list(INVARIANTS),
        "observations": {name: archive.pin(f"{name}.json", body) for name, body in OBSERVATIONS.items()},
        "base": archive.pin("base.json", base), "domain": archive.pin("domain.json", DOMAIN),
    }
    claim = {"run": RUN, "cut": CUT["id"], "batch": f"batch-{STEP}", "members": [STEP], "subsets": [
        {"members": [STEP], "effects": effects, "variant": archive.pin(f"variant-{len(effects)}.json", variant),
         "certificate": archive.pin(f"certificate-{len(effects)}.json", cert)}
        for effects, cert, variant in prefixes]}
    return archive, context, archive.pin("claim.json", claim)


@pytest.mark.xfail(strict=True, raises=ImportError,
                   reason="Waits for checker/tests/test_round_verifier.py--test_round_verifier_replays_the_choice "
                          "(same module rezono_checker.rounds). Then rebuild the visible boundaries of a step with "
                          "several effects from the retained domain: one certificate from the base per nonempty "
                          "prefix of its plans, in their fixed order, as decisions/admission-transport.md section 7 "
                          "fixes. Checker only.")
def test_round_verifier_rebuilds_the_boundaries_of_a_multi_effect_step():
    # Control: both prefix certificates are valid on their own.
    from rezono_checker.transition import check_transition_certificate
    base, prefixes = boundaries()
    context = {"manifest": MANIFEST, "cut": CUT, "definition_sha256": canonical_sha256(PROGRAM),
               "observations": OBSERVATIONS, "program": PROGRAM, "invariants": INVARIANTS}
    for _, cert, variant in prefixes:
        assert check_transition_certificate(cert, context, base, variant)["valid"]
    assert prefixes[0][1]["expected_old"] == [row_ref("link__tail", OLD)]

    from rezono_checker.rounds import Unverified, verify_round

    archive, retained, claim = fixture(prefixes)
    assert verify_round(claim, [retained], set(), archive.__getitem__) == (
        claim["sha256"], RUN, CUT["id"], f"batch-{STEP}", (STEP,))

    # Without the intermediate boundary only the final state is shown: refused.
    archive, retained, claim = fixture(prefixes[1:])
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [retained], set(), archive.__getitem__)
    assert refused.value.code == "round_boundary_missing"

    # A prefix certificate that binds the step name instead of its plans' digest is refused.
    (effects, cert, variant), last = prefixes
    archive, retained, claim = fixture([(effects, cert | {"effect": STEP}, variant), last])
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [retained], set(), archive.__getitem__)
    assert refused.value.code == "certificate_effect_mismatch"
