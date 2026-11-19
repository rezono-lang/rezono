import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read list and record cells and a dash in a fact table in rezono/src/module-facts.ts. Read decisions/language-facts.md, including Writing a record cell. Waits for test_fact_provenance while it owns module-facts.ts.",
)
def test_structured_fact():
    assert_reader_case("structured_fact")
