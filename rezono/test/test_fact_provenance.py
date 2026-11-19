import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read a source declaration (a new rezono/src/module-source.ts, registered in module-components.ts) and the @ citation and @ columns of a fact table in rezono/src/module-facts.ts. Read decisions/language-fact-provenance.md.",
)
def test_fact_provenance():
    assert_reader_case("fact_provenance")
