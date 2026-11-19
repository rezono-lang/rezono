import pytest

from reader_case import assert_reader_case


def test_composite_key():
    assert_reader_case("composite_key")
