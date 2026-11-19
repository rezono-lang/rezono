import pytest

from reader_case import assert_reader_case


def test_prefixed_type():
    assert_reader_case("prefixed_type")
