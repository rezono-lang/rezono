import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement abstract kind in rezono/src. Read decisions/language-kinds.md. Waits for test_embedded_relation (shared module reader and printer).")
def test_abstract_kind():
    assert_reader_case("abstract_kind")
