import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement composite key in rezono/src. Read decisions/language-keys.md. Waits for independent module reader and printer registrations. Use the file priority in docs/rezono/language-coverage.md.")
def test_composite_key():
    assert_reader_case("composite_key")
