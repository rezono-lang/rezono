import pytest

from reader_case import assert_reader_case


def test_native_rule_reader_roundtrip():
    assert_reader_case("native_rule_reader_roundtrip")
