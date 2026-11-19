"""A value that is not known shows the sign of its state and its reason, and no digit
(decisions/viewer-slip.md, "The lines").

tests/fixtures/slip: item-c has no amount, and recorded_amount is an open relation, so capped_amount for item-c
is unknown with the reason the publication gives; both its steps are unknown too.
"""

import re

import pytest
from slip_support import MissingSlipPage, lines, publish_main, render

REASON = "fact recorded_amount.amount is missing"


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "extra: decisions/viewer-slip.md: Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled and, for the page itself, "
        "tests/slip/test_slip_rule_row.py--test_slip_rule_row. "
        "Then draw a value whose state is not known in viewer/slip/ with data-state, data-reason and the sign "
        "of its state from the key of std-view, and no digit, as decisions/viewer-slip.md says. Expectation: "
        "tests/fixtures/slip, item-c without an amount."
    ),
)
def test_unknown_shows_no_digit(tmp_path):
    store, _ = publish_main(tmp_path)
    page = render(store, "reader", row={"relation": "calc__capped_amount", "key": ["item-c", "", "unknown", REASON]})
    slip = page["doc"].one("table", data_sheet="slip")
    cells = [line.one("td", data_part="value") for line in lines(slip)]
    assert len(cells) == 2
    for cell in cells:
        assert cell.attrs["data-state"] == "unknown"
        assert cell.attrs["data-reason"] == REASON
        assert cell.all(data_sign=True), "the sign of its state"
        assert not re.search(r"[0-9]", cell.text()), cell.text()
