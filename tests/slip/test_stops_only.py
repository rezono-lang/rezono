"""What if, on the line (decisions/viewer-slip.md, "What if, on the line"): the control offers only published
stops, shows a red and a not computed stop as such, shows every stop as unavailable for a role that does not read
every relation in full, and shows the fold from the difference of the selected stop.

tests/fixtures/slip, written here by hand: the sweep moves the amount of item-a (12 on main) over 0 to 30 by 5;
15 is taken out of the store (not computed) and 30 is red. At 20 the fold strikes 12 and shows 20.
"""

import re

import pytest
import yaml
from slip_support import (
    ROOT,
    MissingSlipPage,
    drop_variant,
    line_ref,
    lines,
    publish_sweeps,
    render,
)

STATUSES = ["green", "green", "green", "not_computed", "green", "green", "red"]


def amount_line(page):
    slip = page["doc"].one("table", data_sheet="slip")
    [line] = [line for line in lines(slip) if line_ref(line) == ("item__amount", ["item-a", "12"])]
    return line


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "extra: decisions/viewer-slip.md: Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled, tests/slip/test_slip_rule_row.py--"
        "test_slip_rule_row (the page), tests/slip/test_variant_difference_local.py--"
        "test_variant_difference_local and tests/slip/test_turn_unknown_neighbour.py--test_turn_unknown_neighbour. "
        "Then put the control of a sweep on the line of its cell in viewer/slip/: one [data-stop] per published "
        "grid value with data-status and data-turn, opened by the key of suppose and moved stop by stop, and the "
        "fold (del for the old value, ins for the new) from the difference of the selected stop "
        "(decisions/viewer-slip.md, What if, on the line). Expectation: tests/fixtures/slip, stops by hand."
    ),
)
def test_stops_only(tmp_path):
    store, _, done = publish_sweeps(tmp_path)
    drop_variant(store, next(vid for vid, _ in done if vid.startswith("v-item_amount-03-")))
    first = render(store, "reader")
    keys = {verb["verb"]: verb["key"] for verb in
            yaml.safe_load((ROOT / "packs" / "std-view" / "sheets.yaml").read_text(encoding="utf-8"))["verbs"]}
    index = int(amount_line(first).attrs["data-line"])
    suppose = {"line": index, "key": keys["suppose"]}

    def stops(page):
        return amount_line(page).all(data_stop=True)

    opened = render(store, "reader", keys=[suppose])
    assert [(s.attrs["data-stop"], s.attrs["data-status"]) for s in stops(opened)] == [
        (str(i), status) for i, status in enumerate(STATUSES)]
    red = stops(opened)[6]
    assert [c.attrs.get("data-status") for c in red.all(data_check=True)].count("red") >= 1

    # The fold at 20 comes from the difference: 12 struck, 20 beside it.
    at = render(store, "reader", keys=[suppose, {"line": index, "stop": 4}])
    cell = amount_line(at).one("td", data_part="value")
    assert re.sub(r"\s+", "", cell.one("del").text()) == "12"
    assert re.sub(r"\s+", "", cell.one("ins").text()) == "20"
    # A red or a not computed stop has no variant, so no fold and no value.
    for stop in (3, 6):
        moved = render(store, "reader", keys=[suppose, {"line": index, "stop": stop}])
        assert not amount_line(moved).all("ins"), stop

    # summary reads the swept cell but not every relation in full: every stop is unavailable.
    other = render(store, "summary", keys=[suppose])
    assert [s.attrs["data-status"] for s in stops(other)] == ["unavailable"] * len(STATUSES)
