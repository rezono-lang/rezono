import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Read a relational rule block in rezono/src. Read decisions/language-rules.md. Waits for independent module reader and printer registrations. Use the file priority in docs/rezono/language-coverage.md.")
def test_relational_rule_block():
    assert_reader_case("relational_rule_block")
