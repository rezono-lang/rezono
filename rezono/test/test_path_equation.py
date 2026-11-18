import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement path equation in rezono/src. Read decisions/language-keys.md. Waits for independent module reader and printer registrations. Use the file priority in docs/rezono/language-coverage.md.")
def test_path_equation():
    assert_reader_case("path_equation")
