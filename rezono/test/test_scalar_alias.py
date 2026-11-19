import pytest

from reader_case import assert_reader_case


def test_scalar_alias():
    assert_reader_case("scalar_alias")
