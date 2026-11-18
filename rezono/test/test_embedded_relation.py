import pytest

from reader_case import assert_reader_case


def test_embedded_relation():
    assert_reader_case("embedded_relation")
