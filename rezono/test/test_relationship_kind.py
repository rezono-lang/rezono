import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read relationship kind into the kind member relationship in rezono/src/module-kind.ts and refuse it with embedded. Read decisions/language-relationship-kinds.md.",
)
def test_relationship_kind():
    assert_reader_case("relationship_kind")
