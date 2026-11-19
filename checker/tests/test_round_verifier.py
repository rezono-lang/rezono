"""The round verifier of decisions/admission-transport.md, section 7.

A round claim names a run, a cut and a chosen batch, with a transition certificate for each visible
subset. The verifier builds its certificate context only from the retained round context, checks every
certificate with check_transition_certificate, and replays the deterministic selection of
decisions/safe-step-rounds.md ("Deterministic selection"): the largest certified batch, then the least
tuple of pack priorities. An alternative that would precede the claimed batch needs refuting evidence;
without it the round is not verified. The certificates reuse the hand-authored transition fixture.
"""

import pytest
from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from test_transition_certificate import (
    CUT,
    DELTA,
    INVARIANTS,
    NEW,
    OBSERVATIONS,
    OLD,
    PROGRAM,
    row_ref,
    snapshot,
)

RUN = CUT["run"]
MANIFEST = "desired-a"
# Width one: every candidate batch is a singleton. Both steps replace the same tail and are safe alone,
# so the pack priority alone decides: replace-link-a (1) precedes move-link-a (2). Each step lists the plan
# hashes of its effects in their fixed order; a certificate binds the digest of the plans it applies.
PLANS = {"replace-link-a": ["plan-replace-link-a"], "move-link-a": ["plan-move-link-a"]}
DOMAIN = {"width": 1, "steps": [{"step": "replace-link-a", "priority": 1, "effects": PLANS["replace-link-a"]},
                                {"step": "move-link-a", "priority": 2, "effects": PLANS["move-link-a"]}]}


class Archive(dict):
    def pin(self, name, value):
        data = value if isinstance(value, bytes) else canonical_bytes(value)
        uri = f"archive/{sha256_hex(data)}"
        self[uri] = data
        return {"file": name, "uri": uri, "sha256": sha256_hex(data)}


def certificate(step, base, variant, **changes):
    return {
        "manifest": MANIFEST, "run": RUN, "cut": CUT["id"], "definition_sha256": canonical_sha256(PROGRAM),
        "base": canonical_sha256(base), "variant": canonical_sha256(variant),
        "rule": "replace_tail", "bindings": {"link": "link-a"}, "effect": canonical_sha256(PLANS[step]),
        "expected_old": [row_ref("link__tail", OLD)], "delta": DELTA,
        "invariants": {name: {"rows": [], "count": "0"} for name in INVARIANTS},
    } | changes


def fixture(step="replace-link-a", run=RUN, **changes):
    """A retained round context and a submitted claim for one singleton batch."""
    archive = Archive()
    base, variant = snapshot("base", OLD), snapshot("variant", NEW)
    context = {
        "run": RUN, "cut": CUT, "manifest": MANIFEST, "definition_sha256": canonical_sha256(PROGRAM),
        "program": archive.pin("program.json", PROGRAM), "invariants": list(INVARIANTS),
        "observations": {name: archive.pin(f"{name}.json", body) for name, body in OBSERVATIONS.items()},
        "base": archive.pin("base.json", base), "domain": archive.pin("domain.json", DOMAIN),
    }
    claim = {
        "run": run, "cut": CUT["id"], "batch": f"batch-{step}", "members": [step],
        "subsets": [{"members": [step], "effects": PLANS[step], "variant": archive.pin("variant.json", variant),
                     "certificate": archive.pin("certificate.json", certificate(step, base, variant, **changes))}],
    }
    return archive, context, archive.pin("claim.json", claim)


def test_round_verifier_replays_the_choice():
    # Control: the fixture's certificate is valid on its own, before it is archived.
    from rezono_checker.transition import check_transition_certificate
    base, variant = snapshot("base", OLD), snapshot("variant", NEW)
    certificate_context = {"manifest": MANIFEST, "cut": CUT, "definition_sha256": canonical_sha256(PROGRAM),
                           "observations": OBSERVATIONS, "program": PROGRAM, "invariants": INVARIANTS}
    assert check_transition_certificate(certificate("replace-link-a", base, variant), certificate_context,
                                        base, variant)["valid"]

    archive, context, claim = fixture()
    from rezono_checker.rounds import Unverified, verify_round

    # The first choice, certified: the round is the digest of the claim bytes.
    assert verify_round(claim, [context], set(), archive.__getitem__) == (
        claim["sha256"], RUN, CUT["id"], "batch-replace-link-a", ("replace-link-a",))

    # The second step is safe too, but the first precedes it and nothing refutes the first.
    archive, context, claim = fixture("move-link-a")
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [context], set(), archive.__getitem__)
    assert refused.value.code == "round_preceded"

    # A certificate for another cut, and a claim for another run, are refused.
    archive, context, claim = fixture(cut="cut-b")
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [context], set(), archive.__getitem__)
    assert refused.value.code == "certificate_invalid"
    archive, context, claim = fixture(effect="replace-link-a")  # the step name instead of its plans' digest
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [context], set(), archive.__getitem__)
    assert refused.value.code == "certificate_effect_mismatch"
    archive, context, claim = fixture(run="run-b")
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [context], set(), archive.__getitem__)
    assert refused.value.code == "round_context_missing"

    # Authority comes from the retained context alone: without it nothing is verified.
    archive, _, claim = fixture()
    with pytest.raises(Unverified) as refused:
        verify_round(claim, [], set(), archive.__getitem__)
    assert refused.value.code == "round_context_missing"
