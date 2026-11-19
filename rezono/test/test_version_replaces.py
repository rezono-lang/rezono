import pytest

from reader_case import assert_reader_case


def test_version_replaces():
    assert_reader_case("version_replaces")
