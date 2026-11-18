import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="Read a named conditional requirement on a kind. Read decisions/language-checks.md.")
def test_conditional_check():
    assert_reader_case("conditional_check")
