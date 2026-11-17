"""AUD-C6: `-0` is no integer anywhere (values.md §6 rule 2, K9): equal meaning, equal bytes. The compiler already
refuses it (`rules.py` INT); the checker refused it only for calculation premises, so `0/1` and `-0/1` hashed apart."""

import json

import pytest

from rezono_checker.canon import number
from rezono_checker.evaluate import _holds, _int
from rezono_checker.snapshots import read_rows


def snapshot(value: dict) -> bytes:
    return json.dumps([{"key": ["a"], "values": {"v": value}}]).encode()


@pytest.mark.parametrize("value", [
    {"state": "known", "minor_units": "-0", "currency": "EUR"},
    {"state": "known", "minor_units": "-0", "scale": 0, "unit": "m"},
    {"state": "known", "numerator": "-0", "denominator": "1"},
    {"state": "known", "numerator": "0", "denominator": "-0"},
])
def test_a_snapshot_with_negative_zero_is_malformed(value):
    with pytest.raises(ValueError):
        read_rows(snapshot(value), "json")


def test_zero_itself_still_reads():
    for value in ({"state": "known", "minor_units": "0", "currency": "EUR"},
                  {"state": "known", "numerator": "0", "denominator": "1"}):
        read_rows(snapshot(value), "json")


@pytest.mark.parametrize("text", ["-0", "-0/1", "0/-0", "-00", "00", "+0"])
def test_negative_zero_is_no_exact_number(text):
    with pytest.raises(ValueError):
        number(text)


def test_a_rule_compares_negative_zero_as_no_integer():
    """A condition orders integers only; `-0` is text, so `-0 < 1` does not hold and `-0` is not `0`."""
    assert _int("-0") is None and _int("0") == 0
    assert not _holds("lt", "-0", "1") and not _holds("eq", "-0", "0")
