"""The verbs on a line (decisions/viewer-slip.md, "The verbs"): why and depends open with their keys, and a verb
whose question the reader does not answer is not shown; a reader that answers one more question makes that verb
appear without a change to the page.

The keys come from `Sheets.verbs` in packs/std-view/sheets.yaml, read here as the oracle. tests/fixtures/slip:
busy(group-a) rests on group_size(group-a, 2), a conclusion, so its line has why and depends; flagged(item-a, 12)
rests on the absent row held(item-a), which the local reader cannot answer `gap` for, and answers-gap.mjs can.
"""

from pathlib import Path

import pytest
import yaml
from slip_support import ROOT, MissingSlipPage, line_ref, lines, publish_main, render

GAP = Path(__file__).with_name("answers-gap.mjs")


def verb_keys() -> dict[str, str]:
    sheets = yaml.safe_load((ROOT / "packs" / "std-view" / "sheets.yaml").read_text(encoding="utf-8"))
    return {verb["verb"]: verb["key"] for verb in sheets["verbs"]}


def verbs(line) -> dict[str, str]:
    return {button.attrs["data-verb"]: button.attrs["data-key"] for button in line.all("button", data_verb=True)}


def line_of(page, relation, key):
    slip = page["doc"].one("table", data_sheet="slip")
    [line] = [line for line in lines(slip) if line_ref(line) == (relation, key)]
    return line


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "M3: decisions/viewer-slip.md: Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled and, for the page itself, "
        "tests/slip/test_slip_rule_row.py--test_slip_rule_row. "
        "Then show on each line of viewer/slip/ the verbs whose question the reader answers for that line, in "
        "the order and with the keys of Sheets.verbs, and open an answer as a table on its key, as "
        "decisions/viewer-slip.md, section The verbs, says. The page holds no name of a question. "
        "Expectation: tests/fixtures/slip and packs/std-view/sheets.yaml."
    ),
)
def test_verbs_that_answer(tmp_path):
    store, _ = publish_main(tmp_path)
    busy = {"relation": "busy", "key": ["group-a"]}
    page = render(store, "reader", row=busy)
    keys = verb_keys()
    line = line_of(page, "group_size", ["group-a", "2"])
    assert verbs(line) == {"why": keys["why"], "depends": keys["depends"]}
    index = int(line.attrs["data-line"])
    opened = render(store, "reader", row=busy, keys=[{"line": index, "key": keys["why"]}])
    assert opened["doc"].one("table", data_answer="grounds").all("th")
    opened = render(store, "reader", row=busy, keys=[{"line": index, "key": keys["depends"]}])
    assert opened["doc"].one("table", data_answer="reach").all("th")

    # The local reader does not answer gap: no `missing` on the absent row. With one more question, it is there.
    plain = render(store, "reader")
    assert "missing" not in verbs(line_of(plain, "held", ["item-a"]))
    more = render(store, "reader", reader=GAP)
    assert verbs(line_of(more, "held", ["item-a"])).get("missing") == keys["missing"]
    assert more["files"] == plain["files"], "the same page answered more, without a change to the page"
