"""Turning points along a published sweep, served by `sweep` from a row (decisions/viewer-slip.md, "Turning
points"): beside a stop without a variant no turning point is marked, and the stop says that it is not known.

tests/fixtures/slip sweeps the amount of item-a over 0, 5, ..., 30. Written here by hand for flagged(item-a, _),
which holds from 10 on: at 0 and 5 it is not there; at 10 it appears (a turn, presence); 15 is taken out of the
store, so it is not computed; 20 stands beside it; 25 is the same proof with another amount; 30 is red (too_large).
"""

import json

import pytest
from slip_support import PACK, ask, drop_variant, publish_sweeps, row_query


class MissingServedTurns(AssertionError):
    """`sweep` from a row gives no turn per stop."""


EXPECTED = [  # (index, status, turn, causes, row key at the stop)
    (0, "green", None, None, None),
    (1, "green", "same", None, None),
    (2, "green", "turns", ["presence"], ["item-a", "10"]),
    (3, "not_computed", "unknown", None, None),
    (4, "green", "unknown", None, ["item-a", "20"]),
    (5, "green", "same", None, ["item-a", "25"]),
    (6, "red", "unknown", None, None),
]


def test_turn_unknown_neighbour(tmp_path):
    store, manifest, done = publish_sweeps(tmp_path)
    drop_variant(store, next(vid for vid, _ in done if vid.startswith("v-item_amount-03-")))
    query = f"/{PACK}/{manifest['id']}/ask/sweep?sweep=item_amount&{row_query('flagged', 'item-a', '12')}"
    reader, summary = (ask(store, role, query)[0] for role in ("reader", "summary"))
    assert reader["status"] == 200, reader
    series = reader["body"]["series"]
    if not any("turn" in cell for cell in series):
        raise MissingServedTurns(str(series)[:400])
    assert reader["body"]["start"] == {"relation": "flagged", "key": '["item-a","12"]'}
    got = [(c["index"], c["status"], c.get("turn"), c.get("causes"),
            None if "row" not in c else json.loads(c["row"]["key"])) for c in series]
    assert got == EXPECTED
    # A role that does not see the status of both stops sees no turning point.
    assert summary["status"] == 200, summary
    assert all(cell.get("turn") in (None, "unknown") for cell in summary["body"]["series"])
