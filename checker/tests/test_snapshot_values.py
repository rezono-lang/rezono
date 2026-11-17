"""Value cells in a JSON snapshot: the four states with their reasons (contracts/value.yaml, B06)."""

import json

import pytest

from rezono_checker.snapshots import read_rows

STATES = [
    {"state": "known", "value": "5"},
    {"state": "known", "value": "5", "reason": "added_later"},
    {"state": "unknown", "reason": "not_assigned"},
    {"state": "not_applicable", "reason": "empty"},
    {"state": "invalid", "reason": "versions_overlap"},
    {"state": "unknown"},
    {"state": "unknown", "currency": "EUR", "reason": "no_row_applies"},
    {"state": "not_applicable", "unit": "kg", "scale": 3, "reason": "empty"},
]


def snapshot(*cells):
    return json.dumps([{"key": [f"k{i}"], "values": {"v": c}} for i, c in enumerate(cells)]).encode()


def test_the_four_states_round_trip_with_their_reasons():
    rows = read_rows(snapshot(*STATES), "json")
    assert [values["v"] for _, values in rows.values()] == STATES


@pytest.mark.parametrize("cell, why", [
    ({"state": "unknown", "value": ""}, "payload"),  # K11: no payload member, not even an empty one
    ({"state": "not_applicable", "minor_units": "0", "currency": "EUR"}, "payload"),
    ({"state": "invalid", "denominator": "1"}, "unexpected fields"),
    ({"state": "unknown", "reason": ""}, "reason code"),  # an empty reason is left out
    ({"state": "unknown", "reason": "owner not assigned"}, "reason code"),
    ({"state": "unknown", "reason": "Not_assigned"}, "reason code"),
    ({"state": "unknown", "reason": 7}, "reason code"),
    ({"state": "known", "value": "5", "reason": "not_assigned"}, "added_later"),
])
def test_malformed_cells_are_refused(cell, why):
    with pytest.raises(ValueError, match=why):
        read_rows(snapshot(cell), "json")


def test_known_empty_text_stays_a_value():
    rows = read_rows(snapshot({"state": "known", "value": ""}), "json")
    assert next(iter(rows.values()))[1]["v"] == {"state": "known", "value": ""}
