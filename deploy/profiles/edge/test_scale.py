"""Synthetic scale reports for the O(page) contract in docs/gui.md."""

import pytest

from scale import check


def measurement(path, key, size):
    return {
        "path": path, "status": 200, "gate_calls": 1, "gate_bytes": size,
        "store_gets": 1, "store_bytes": size, "store_listed": 0,
        "store_reads": [[key, size]],
    }


def sample():
    return [
        measurement("/map", "map/page", 100),
        measurement("/twin", "twin/page", 100),
        measurement("control:map", "map/snapshot", 100),
        measurement("control:twin", "twin/snapshot", 2050),
    ]


def test_page_can_stay_small_while_control_grows():
    rows = sample()
    assert check(rows, "map", "twin")[1] == []
    rows[-1] = measurement("control:twin", "twin/snapshot", 1174)
    assert check(rows, "map", "twin")[1]


@pytest.mark.xfail(strict=True, reason="Scope baseline reads to the named pack in deploy/profiles/edge/scale.py. Read docs/gui.md on work per request.")
def test_sibling_route_cannot_supply_baseline_reads():
    rows = sample()
    rows[1] = measurement("/twin", "twin/extra", 100)
    assert check(rows, "map", "twin")[1]
    rows.append(measurement("/maple", "map/extra", 100))
    assert check(rows, "map", "twin")[1]


def test_unmatched_snapshot_is_not_a_growth_measurement():
    rows = sample()
    rows[-1] = measurement("control:twin", "twin/different", 100)
    assert check(rows, "map", "twin")[1]
