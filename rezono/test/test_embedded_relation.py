import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement embedded relation in rezono/src. Read decisions/language-relations.md. Waits for test_embedded_kind (shared module reader and printer).")
def test_embedded_relation():
    assert_reader_case("embedded_relation")
