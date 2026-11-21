"""A value that is not known shows the sign of its state and its reason, and no digit
(decisions/viewer-slip.md, "The lines").

tests/fixtures/slip: item-c has no amount, and recorded_amount is an open relation, so capped_amount for item-c
is unknown with the reason the publication gives; both its steps are unknown too.
"""

import re

import pytest
from slip_support import MissingSlipPage, lines, publish_main, render

REASON = "fact recorded_amount.amount is missing"


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
