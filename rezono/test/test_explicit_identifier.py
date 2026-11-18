import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement explicit identifier in rezono/src. Read decisions/language-kinds.md.")
def test_explicit_identifier():
    assert_reader_case("explicit_identifier")
