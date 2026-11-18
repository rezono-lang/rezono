import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement path equation in rezono/src. Read decisions/language-keys.md. Waits for test_composite_key (shared module reader and printer).")
def test_path_equation():
    assert_reader_case("path_equation")
