import pytest

from reader_case import assert_reader_case


def test_structured_fact():
    assert_reader_case("structured_fact")
