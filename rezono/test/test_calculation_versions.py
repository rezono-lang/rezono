import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M3: decisions/language-calculations.md: Read a version line without a value as a block of "
           "definitions, `unit TEXT` under a derived value, and `overrides NAME because \"reason\"` at the end of a "
           "definition line, in rezono/src/module-derived.ts and rezono/src/module-version.ts, as the section "
           "Versions with definitions shows; refuse definitions beside versions, an override that names no "
           "definition of the same version, and an override without a reason. Admit the new members in "
           "contracts/rezono-module.yaml. Waits for test_version_replaces while it owns module-version.ts.",
)
def test_calculation_versions():
    assert_reader_case("calculation_versions")
