import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement embedded kind in rezono/src. Read decisions/language-kinds.md. Waits for test_explicit_identifier (shared module reader and printer).")
def test_embedded_kind():
    assert_reader_case("embedded_kind")
