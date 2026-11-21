"""The slip of a rule row: the sentence and the lines (decisions/viewer-slip.md, "The sentence" and "The lines").

Expectations are written by hand from tests/fixtures/slip: item-a has amount 12 and no hold, so it is flagged;
group-a has two items. The lines are also held against the reader's own `grounds` answer, which the page must
show as it is: none added, none dropped, in the answer's order.
"""

import json
import re

import pytest
from slip_support import (
    PACK,
    MissingSlipPage,
    ask,
    line_ref,
    lines,
    publish_main,
    render,
    row_query,
)


def normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def distance_one(store, relation, *key):
    [answer] = ask(store, "reader", f"/{PACK}/m-1/ask/grounds?{row_query(relation, *key)}")
    assert answer["status"] == 200, answer
    return [(n["relation"], json.loads(n["key"])) for n in answer["body"]["nodes"] if n["distance"] == 1]


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "M3: decisions/viewer-slip.md: Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash and "
        "tests/slip/test_message_filled.py--test_message_filled. "
        "Then build the page in viewer/slip/ (Svelte 5, its own package.json and lockfile, outside "
        "viewer/src/lib) with the test entry viewer/slip/bin/render.ts and the marks of decisions/viewer-slip.md, "
        "section The page and how it gets its answers. This test is the first of the page: the other page tests "
        "wait for it. Expectation: tests/fixtures/slip, sentences and rows written by hand."
    ),
)
def test_slip_rule_row(tmp_path):
    store, manifest = publish_main(tmp_path)
    assert manifest["id"] == "m-1"

    # Without a row the slip opens on the one row of the home claim the role reads: flagged(item-a, 12).
    page = render(store, "reader")
    slip = page["doc"].one("table", data_sheet="slip")
    sentence = page["doc"].one(data_part="sentence")
    assert normal(sentence.text()) == "Item item-a is flagged with amount 12, and nothing holds it."
    rows = lines(slip)
    expected = [("held", ["item-a"]), ("item__amount", ["item-a", "12"])]
    assert [line_ref(line) for line in rows] == expected == distance_one(store, "flagged", "item-a", "12")
    assert [line.attrs["data-polarity"] for line in rows] == ["negative", "positive"]
    assert [line.attrs["data-depth"] for line in rows] == ["0", "0"]
    # Both variables are bound by the first atom of the rule's body, item__amount(i, a): premise position 0.
    links = sentence.all("a", data_line=True)
    assert [link.attrs["data-line"] for link in links] == ["1", "1"]
    assert [line.attrs["data-line"] for line in rows] == ["0", "1"]

    # An aggregate: its contributors stand under its total, which is the published result.
    page = render(store, "reader", row={"relation": "group_size", "key": ["group-a", "2"]})
    slip = page["doc"].one("table", data_sheet="slip")
    assert normal(page["doc"].one(data_part="sentence").text()) == "Group group-a has 2 items."
    every = lines(slip)
    totals = [line for line in every if line.attrs.get("data-part") == "total"]
    assert len(totals) == 1
    total = totals[0]
    assert normal(total.one("td", data_part="value").text()) == "2"
    rows = [line for line in every if line.attrs.get("data-part") != "total"]
    assert [(line_ref(line), line.attrs["data-depth"]) for line in rows] == [
        (("group", ["group-a"]), "0"),
        (("item__group", ["item-a", "group-a"]), "1"),
        (("item__group", ["item-b", "group-a"]), "1"),
    ]
    assert [line_ref(line) for line in rows] == distance_one(store, "group_size", "group-a", "2")
    assert every.index(total) == every.index(rows[1]) - 1, "the contributors follow their total"
