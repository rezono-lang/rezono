import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read the stage context during and the setup context in of a fact row in rezono/src/module-version.ts, and "
           "admit the members during and in on FactRow in contracts/rezono-module.yaml. Read "
           "decisions/language-dated-facts.md, section Stage and setup contexts. No dependency.",
)
def test_fact_context_axes():
    assert_reader_case("fact_context_axes")
