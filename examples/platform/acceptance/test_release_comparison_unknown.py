"""A register entry that cannot be compared with the publisher is reported as unknown, never as agreement.

Expectation source: decisions/platform-release-comparison-unknown.md and the open-world description of
`ProductReleaseReference.published` in schema/keycloak_release.yaml ("Its absence leaves the comparison
unknown"). The expected rows are written here from the authored register and announcement facts.
"""

import json

import pytest
from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch
from rules_support import State, states

from query_fixture import ROOT

UNKNOWN = "product_release_date_comparison_unknown"
DRIFT = "product_release_date_drift"
REFERENCE = "keycloak-26.0.0-register"
SOURCE = "keycloak-26.0.0-release-source"
REGISTER_DATE_MISSING = (REFERENCE, "keycloak", "26.0.0", "register-date-missing")
OBSERVATION_MISSING = (REFERENCE, "keycloak", "26.0.0", "observation-missing")


def _outcomes(program, rows):
    with batch.connect(program, rows, threads=1) as connection:
        batch.compute(connection, program)
        return batch.read(connection, program, [DRIFT, UNKNOWN])


def _without(rows, *relations):
    return {relation: values for relation, values in rows.items() if relation not in relations}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Derive product_release_date_comparison_unknown(reference, product_id, version, reason) in "
    "rules/keycloak_release.dl: 'register-date-missing' for a register reference without a published date, "
    "'observation-missing' for one with no observed release of the same product and version. "
    "Read decisions/platform-release-comparison-unknown.md."))
def test_missing_ground_makes_the_release_comparison_unknown():
    model, program, (state,) = states(ROOT)
    assert UNKNOWN in program.relations, f"Missing derived relation: {UNKNOWN}"
    base = state.base

    # Both grounds present and equal: neither drift nor unknown.
    assert _outcomes(program, base) == {DRIFT: set(), UNKNOWN: set()}

    # A changed register date is drift, not unknown.
    changed = base | {"product_release_reference__published": [(REFERENCE, "2024-10-05")]}
    assert _outcomes(program, changed)[UNKNOWN] == set()

    # Each missing ground gives its own reason; drift stays empty.
    assert _outcomes(program, _without(base, "product_release_reference__published")) == {
        DRIFT: set(), UNKNOWN: {REGISTER_DATE_MISSING}}
    assert _outcomes(program, _without(base, "product_release_source")) == {
        DRIFT: set(), UNKNOWN: {OBSERVATION_MISSING}}
    assert _outcomes(program, _without(base, "product_release_reference__published", "product_release_source")) == {
        DRIFT: set(), UNKNOWN: {REGISTER_DATE_MISSING, OBSERVATION_MISSING}}

    # An announcement of another version does not close the comparison.
    other_version = base | {"product_release_source__version": [(SOURCE, "26.0.1")]}
    assert _outcomes(program, other_version)[UNKNOWN] == {OBSERVATION_MISSING}

    # Without a register reference there is nothing to compare, so nothing is unknown.
    assert _outcomes(program, _without(base, "product_release_reference"))[UNKNOWN] == set()

    # The unknown row rests on the register entry it describes, and its proof checks.
    label = "register-date-missing"
    missing = State(model, program, label, _without(base, "product_release_reference__published"))
    assert missing.derived[UNKNOWN] == {REGISTER_DATE_MISSING}
    proof = missing.proof(UNKNOWN, REGISTER_DATE_MISSING)
    manifest, read = missing.manifest()
    report = check(proof, manifest, load_rules(model.rules), read)
    assert report["valid"] and not report["findings"], report["findings"]
    premises = {(item["row"]["relation"], tuple(json.loads(item["row"]["key"])))
                for witness in proof["witnesses"] for item in witness["premises"]}
    assert {("product_release_reference", (REFERENCE,)),
            ("product_release_reference__product", (REFERENCE, "keycloak")),
            ("product_release_reference__version", (REFERENCE, "26.0.0"))} <= premises
