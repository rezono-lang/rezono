"""A supply is verified from an observed signature, complete only within a verifier's scan
(decisions/platform-facts-not-conclusions.md, section 7).

The expected rows are the independent reference rows of oracle-rows.json, which the oracle computes from
Artifact.signed until a planner retires it; the observations are the scenario's, as section 7 states them: one scan
that covers both artifacts, and one signature on the artifact of shop.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parent
SIGNATURE = "artifact_signature"


def _rows():
    from rezono_compiler import scenarios
    from rules_support import states

    model, prog, _ = states(PLATFORM)
    label, raw = next(iter(scenarios.states(model, PLATFORM)))
    return model, prog, label, {table: list(values) for table, values in raw.items()}


def _derive(model, prog, label, rows):
    from rules_support import State

    return State(model, prog, label, rows).derived


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/platform-facts-not-conclusions.md, section 7. Add schema/artifact_signature.yaml in the layer "
    "observation (ArtifactSignature, world open, with artifact and scan; SignatureScan with covers), the scenario's "
    "observations in facts/artifact_signature.yaml (scan `scan-1` covering `a-shop` and `a-lab`, signature `sig-1` "
    "on `a-shop` in `scan-1`) with a `synthetic` sidecar, `arrow.many.total` in messages/en.mf2, and rules in which "
    "verified reads the observed signature, supply_unknown names a service whose artifact no scan covers, and "
    "unverified_supply leaves those out. Keep Artifact.signed: a planner retires it."))
def test_supply_is_verified_from_observed_signatures():
    reference = {tuple(row) for row in
                 json.loads((PLATFORM / "oracle-rows.json").read_text(encoding="utf-8"))["unverified_supply"]}
    model, prog, label, rows = _rows()
    kind = model.kinds.get(SIGNATURE)
    assert kind is not None, "Missing kind ArtifactSignature"
    assert (kind.layer, kind.world) == ("observation", "open"), (kind.layer, kind.world)
    artifact, covers = model.slot(SIGNATURE, "artifact"), model.slot("signature_scan", "covers")
    assert artifact is not None and artifact.arrow and artifact.range == "artifact"
    assert covers is not None and covers.multivalued and covers.range == "artifact"

    derived = _derive(model, prog, label, rows)
    assert derived["verified"] == {("shop",)}
    assert derived["unverified_supply"] == reference
    assert not derived.get("supply_unknown"), derived.get("supply_unknown")

    # The written flag decides nothing, while it is still written.
    if "artifact__signed" in rows:
        flipped = dict(rows, artifact__signed=[(x, "no" if value == "yes" else "yes")
                                              for x, value in rows["artifact__signed"]])
        changed = _derive(model, prog, label, flipped)
        assert (changed["verified"], changed["unverified_supply"]) == (derived["verified"], reference)

    for_service = rows["artifact__for_service"]
    lab = {x for x, service in for_service if service == "lab"}
    shop = {x for x, service in for_service if service == "shop"}

    # Outside every scan a missing signature says nothing: lab is unknown, not unverified.
    unscanned = dict(rows, signature_scan__covers=[(scan, x) for scan, x in rows["signature_scan__covers"]
                                                   if x not in lab])
    changed = _derive(model, prog, label, unscanned)
    assert changed["supply_unknown"] == {("lab",)}
    assert changed["unverified_supply"] == reference - {("lab",)}

    # Inside the scan it is known: without the signature on its artifact, shop is unverified.
    seen = {o for o, x in rows[f"{SIGNATURE}__artifact"] if x in shop}
    unsigned = {table: [row for row in values if row[0] not in seen]
                if table == SIGNATURE or table.startswith(SIGNATURE + "__") else values
                for table, values in rows.items()}
    changed = _derive(model, prog, label, unsigned)
    assert not changed.get("verified")
    assert changed["unverified_supply"] == reference | {("shop",)}
