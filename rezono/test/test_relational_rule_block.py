import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Read a relational rule block in rezono/src. Read decisions/language-rules.md. Waits for test_path_equation (shared reader and printer).")
def test_relational_rule_block():
    assert_reader_case("relational_rule_block")
