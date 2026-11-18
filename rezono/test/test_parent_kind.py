import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement parent kind in rezono/src. Read decisions/language-kinds.md. Waits for test_abstract_kind (shared module reader and printer).")
def test_parent_kind():
    assert_reader_case("parent_kind")
