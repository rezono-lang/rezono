import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement parent kind in rezono/src. Read decisions/language-kinds.md. Waits for independent module reader and printer registrations. Use the file priority in docs/rezono/language-coverage.md.")
def test_parent_kind():
    assert_reader_case("parent_kind")
