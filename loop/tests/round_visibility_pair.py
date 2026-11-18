"""Proof fixture for the existing independent two-snapshot verifier."""

from typing import NamedTuple

from rezono_canon import canonical_json, canonical_sha256, sha256_hex

from round_visibility_cases import Effect, LANES, LANE_PHASE, RUN, SCOPE, Readback, State


def _relation(name, role, columns, *, invariant=False):
    signature = {"name": name, "role": role, "key": [{"name": column, "type": "string"} for column in columns]}
    return {**signature, "invariant": True} if invariant else signature


def _literal(relation, *terms, negative=False):
    return {"relation": relation, "terms": list(terms),
            "polarity": "negative" if negative else "positive", "stratum": "0"}


def _rule(name, head, body, *, stratum="0"):
    return {"id": name, "stratum": stratum, "head": {"relation": name, "terms": list(head)}, "body": body}


PROGRAM = {
    "format": "rezono.rules/1",
    "relations": [
        _relation(LANE_PHASE, "base", ("lane", "phase")),
        _relation("expected_lane", "base", ("lane",)),
        _relation("lane_present", "derived", ("lane",)),
        _relation("missing_lane", "derived", ("lane",), invariant=True),
        _relation("outage", "derived", ("left", "right"), invariant=True),
    ],
    "rules": [
        _rule("lane_present", ("?lane",), [_literal(LANE_PHASE, "?lane", "?phase")]),
        _rule("missing_lane", ("?lane",), [_literal("expected_lane", "?lane"),
                                         _literal("lane_present", "?lane", negative=True)], stratum="1"),
        _rule("outage", LANES, [_literal(LANE_PHASE, lane, "offline") for lane in LANES]),
    ],
}
DEFINITION = canonical_sha256(PROGRAM)
MANIFEST = "desired-lanes"
INVARIANTS = ("missing_lane", "outage")


def _row(relation, cells):
    return {"relation": relation, "key": canonical_json(list(cells))}


def _snapshot(label: str, state: State) -> dict:
    phases = list(zip(LANES, state, strict=True))
    return {
        "id": label,
        # A submitted certificate claims no violation. The verifier must reconstruct it.
        "rows": {LANE_PHASE: phases, "expected_lane": [(lane,) for lane in LANES],
                 "lane_present": [(lane,) for lane in LANES], "missing_lane": [], "outage": []},
        "witnesses": [
            {"rule_id": "lane_present", "conclusion": _row("lane_present", (lane,)),
             "bindings": [{"variable": "?lane", "value": lane}, {"variable": "?phase", "value": phase}],
             "premises": [{"row": _row(LANE_PHASE, (lane, phase)), "polarity": "positive", "stratum": 0}]}
            for lane, phase in phases
        ],
    }


class PairEvidence(NamedTuple):
    certificate: dict
    context: dict
    base: dict
    variant: dict


def pair_evidence(readback: Readback, effects: tuple[Effect, ...], target: State) -> PairEvidence:
    """Bind authored exact rows and unchanged observation bytes to one claimed transition."""
    base = _snapshot("base", readback.state)
    variant = _snapshot("variant", target)
    observation = readback.source_bytes()
    context = {
        "manifest": MANIFEST, "definition_sha256": DEFINITION, "program": PROGRAM, "invariants": INVARIANTS,
        "cut": {"id": readback.cut, "run": RUN, "scope": SCOPE, "observation_sha256": sha256_hex(observation)},
        "observations": {f"read-{readback.cut}": observation},
    }
    certificate = {
        "manifest": MANIFEST, "definition_sha256": DEFINITION, "run": RUN, "cut": readback.cut,
        "base": canonical_sha256(base), "variant": canonical_sha256(variant),
        "rule": "replace-lane", "bindings": {effect.lane: effect.step for effect in effects},
        "effect": canonical_sha256([effect.plan_hash for effect in effects]),
        "expected_old": [_row(LANE_PHASE, effect.old_row) for effect in effects],
        "delta": [change for effect in effects for change in effect.delta],
        "invariants": {name: {"rows": [], "count": "0"} for name in INVARIANTS},
    }
    return PairEvidence(certificate, context, base, variant)
