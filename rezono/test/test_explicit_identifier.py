import pytest

from reader_case import assert_reader_case


def test_explicit_identifier():
    assert_reader_case("explicit_identifier")
