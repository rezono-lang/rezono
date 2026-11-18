import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement composite key in rezono/src. Read decisions/language-keys.md. Waits for test_scalar_alias (shared module reader and printer).")
def test_composite_key():
    assert_reader_case("composite_key")
