import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read and print native rule heads and guards in rezono/src. Read decisions/language-native-rules.md.",
)
def test_native_rule_reader_roundtrip():
    assert_reader_case("native_rule_reader_roundtrip")
