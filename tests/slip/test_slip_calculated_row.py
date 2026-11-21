"""The slip of a calculated row (decisions/viewer-slip.md, "The lines"): the steps of its CalcWitness, in their
order, nested by path; a constant has no step and so no line.

tests/fixtures/slip/calc/capped.yaml: capped_amount = min(recorded_amount.amount, 20). For item-a (amount 12)
that is two steps, written here by hand: the min at depth 0 and its first argument at depth 1. The constant 20,
the second argument, has no line.
"""

import re

import pytest
from slip_support import MissingSlipPage, lines, publish_main, render


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "M3: decisions/viewer-slip.md: Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled and, for the page itself, "
        "tests/slip/test_slip_rule_row.py--test_slip_rule_row. "
        "Then show a calculated row in viewer/slip/ as decisions/viewer-slip.md, sections The sentence and The "
        "lines, say: the rule's name and its value, and one line per step with data-path and data-depth. "
        "Expectation: tests/fixtures/slip/calc/capped.yaml, steps written by hand."
    ),
)
def test_slip_calculated_row(tmp_path):
    store, _ = publish_main(tmp_path)
    page = render(store, "reader", row={"relation": "calc__capped_amount", "key": ["item-a", "12", "known", ""]})
    slip = page["doc"].one("table", data_sheet="slip")
    got = [(line.attrs["data-path"], line.attrs["data-depth"],
            re.sub(r"\s+", " ", line.one("td", data_part="value").text()).strip()) for line in lines(slip)]
    assert got == [("at_most_twenty/value", "0", "12"), ("at_most_twenty/value/0", "1", "12")]
    assert not slip.all("tr", data_path="at_most_twenty/value/1"), "a constant has no line"
