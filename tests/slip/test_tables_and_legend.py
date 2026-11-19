"""The slip and every answer are tables with headers, and every sign drawn is in the legend
(decisions/viewer-slip.md, "Tables, legend, keys and language"). tests/fixtures/slip, with the keys of
packs/std-view/sheets.yaml."""

import pytest
import yaml
from slip_support import ROOT, MissingSlipPage, line_ref, lines, publish_main, render


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled and, for the page itself, "
        "tests/slip/test_slip_rule_row.py--test_slip_rule_row. "
        "Then draw the slip and each answer in viewer/slip/ as a table with a header row, and a legend "
        "table[data-part=legend] with one row per sign the page draws, from the key of std-view "
        "(decisions/viewer-slip.md). Expectation: tests/fixtures/slip."
    ),
)
def test_tables_and_legend(tmp_path):
    store, _ = publish_main(tmp_path)
    row = {"relation": "busy", "key": ["group-a"]}
    first = render(store, "reader", row=row)
    sheets = yaml.safe_load((ROOT / "packs" / "std-view" / "sheets.yaml").read_text(encoding="utf-8"))
    keys = {verb["verb"]: verb["key"] for verb in sheets["verbs"]}
    [line] = [line for line in lines(first["doc"].one("table", data_sheet="slip"))
              if line_ref(line) == ("group_size", ["group-a", "2"])]
    index = int(line.attrs["data-line"])
    pages = [first, render(store, "reader"),
             render(store, "reader", row={"relation": "calc__capped_amount",
                                          "key": ["item-c", "", "unknown", "fact recorded_amount.amount is missing"]}),
             render(store, "reader", row=row, keys=[{"line": index, "key": keys["why"]}]),
             render(store, "reader", row=row, keys=[{"line": index, "key": keys["depends"]}])]
    answers = 0
    for page in pages:
        doc = page["doc"]
        legend = doc.one("table", data_part="legend")
        listed = {entry.attrs["data-sign"] for entry in legend.all("tr", data_sign=True)}
        drawn = {node.attrs["data-sign"] for node in doc.all(data_sign=True) if node.ancestor("table") is not legend}
        assert drawn and drawn <= listed, sorted(drawn - listed)
        for table in doc.all("table"):
            assert table.all("th"), f"a table without headers: {table.attrs}"
        assert doc.one("table", data_sheet="slip")
        answers += len(doc.all("table", data_answer=True))
    assert answers == 2
