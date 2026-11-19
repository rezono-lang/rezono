import pytest

from reader_case import assert_reader_case


def test_schema_mappings():
    assert_reader_case("schema_mappings")
