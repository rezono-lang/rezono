"""The slip and every answer are tables with headers, and every sign drawn is in the legend
(decisions/viewer-slip.md, "Tables, legend, keys and language"). tests/fixtures/slip, with the keys of
packs/std-view/sheets.yaml."""

import pytest
import yaml
from slip_support import ROOT, MissingSlipPage, line_ref, lines, publish_main, render


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
