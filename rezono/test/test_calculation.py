import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read output and definition lines under a derived value in rezono/src/module-derived.ts. Read decisions/language-calculations.md.",
)
def test_calculation():
    assert_reader_case("calculation")
