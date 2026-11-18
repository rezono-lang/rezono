import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read a row-backed parameter, from Kind.slot by nameSlot, into the member source in rezono/src/module-parameter.ts. Read decisions/language-parameters.md.",
)
def test_parameters():
    assert_reader_case("parameters")
