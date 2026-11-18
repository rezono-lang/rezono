import pytest

from reader_case import assert_reader_case


def test_schema_metadata():
    assert_reader_case("schema_metadata")
