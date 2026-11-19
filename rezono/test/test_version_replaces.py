import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M3: Read version N replaces M into the version member replaces in rezono/src/module-version.ts, and admit it "
           "on Version in contracts/rezono-module.yaml. Read decisions/language-parameters.md, section Explicit "
           "replacement. Waits for test_fact_context_axes while it owns module-version.ts.",
)
def test_version_replaces():
    assert_reader_case("version_replaces")
