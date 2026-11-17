"""A sheet with lanes and lines of relations (a Flow) is checked like any sheet (rede_checker.views, check_view):
a line is rows the role reads of its sign, a lane or a group is a cell of a row the role reads (or an unknown
lane), and every node lies inside its lane and its group. No binding is needed. Negative cases first."""

import copy
import hashlib
import json

from rede_checker.views import _edge, check_view

# As the compiled bundle names them: kind relations and slot tables.
BUNDLE = {
    "kinds": [{"id": "posting"}, {"id": "account"}, {"id": "transfer"}, {"id": "entry"}],
    "attributes": [{"table": "account__kind", "enum": "account_kind"}, {"table": "account__title"},
                   {"table": "transfer__amount", "kind": "transfer"}],
    "relations": [{"id": "period_line", "columns": [{"name": "period", "type": "string"}, {"name": "posting", "type": "string"},
                                                 {"name": "account", "type": "string"}, {"name": "signed", "type": "integer"}]}],
    "arrows": [{"id": "transfer.from", "table": "transfer__from", "kind": "transfer", "target": "account"},
               {"id": "transfer.to", "table": "transfer__to", "kind": "transfer", "target": "account"},
               {"id": "posting.entry", "table": "posting__entry", "kind": "posting", "target": "entry"},
               {"id": "posting.account", "table": "posting__account", "kind": "posting", "target": "account"}],
    # Transfer is a link kind: its key holds its two arrows.
    "unique_keys": [{"kind": "transfer", "slots": ["transfer.from", "transfer.to"]}],
}
ROWS = {
    "posting": [["p1"], ["p2"]],
    "account": [["a1"], ["a2"], ["a3"]],
    "account__kind": [["a1", "asset"], ["a2", "revenue"]],
    "account__title": [["a1", "Kas"]],
    # Two rows of one pair; one to an account the role does not read.
    "period_line": [["2024", "p1", "a1", "5"], ["2025", "p1", "a1", "7"], ["2025", "p2", "a1", "3"], ["2025", "p1", "secret", "1"]],
    # A link: transfer t1 from a1 to a2.
    "transfer": [["t1"]],
    "transfer__from": [["t1", "a1"]],
    "transfer__to": [["t1", "a2"]],
    "transfer__amount": [["t1", "9"]],
    # Both postings in entry e1; p1 books on a3.
    "entry": [["e1"]],
    "posting__entry": [["p1", "e1"], ["p2", "e1"]],
    "posting__account": [["p1", "a3"]],
}
SCREENED = "screened/posting/p1/period_line"
SHEET, TILE = "flow.ledger", 512
NODES = [
    {"id": "posting/p1", "x": 10, "y": 10, "width": 40, "height": 20, "status": "valid", "lane": {"relation": "posting"},
     "group": {"relation": "posting__entry", "value": "e1"}},
    {"id": "posting/p2", "x": 10, "y": 40, "width": 40, "height": 20, "status": "valid", "lane": {"relation": "posting"},
     "group": {"relation": "posting__entry", "value": "e1"}},
    {"id": SCREENED, "x": 10, "y": 70, "width": 40, "height": 20, "status": "valid"},
    {"id": "account/a1", "x": 100, "y": 10, "width": 40, "height": 20, "status": "valid",
     "name": [{"relation": "account__title", "id": "a1", "value": "Kas"}], "lane": {"relation": "account__kind", "value": "asset"}},
    {"id": "account/a2", "x": 200, "y": 10, "width": 40, "height": 20, "status": "valid", "lane": {"relation": "account__kind", "value": "revenue"}},
    {"id": "account/a3", "x": 300, "y": 10, "width": 40, "height": 20, "status": "valid", "lane": {"unknown": True}},
]
EDGES = [
    {"id": "posting/p1->period_line->account/a1", "source": "posting/p1", "target": "account/a1", "arrow": "period_line", "points": [], "rows": 2,
     "quantity": {"slot": "signed", "value": "12"}, "width": 4},
    {"id": "posting/p2->period_line->account/a1", "source": "posting/p2", "target": "account/a1", "arrow": "period_line", "points": []},
    {"id": f"posting/p1->period_line->{SCREENED}", "source": "posting/p1", "target": SCREENED, "arrow": "screened", "points": []},
    {"id": "account/a1->transfer__to->account/a2", "source": "account/a1", "target": "account/a2", "arrow": "transfer__to", "points": [],
     "quantity": {"slot": "transfer__amount", "value": "9"}},
]
BANDS = [
    {"key": "kind:posting", "axis": "x", "from": 0, "to": 75},
    {"key": "enum:account_kind:asset", "axis": "x", "from": 75, "to": 170},
    {"key": "enum:account_kind:revenue", "axis": "x", "from": 170, "to": 270},
    {"key": "?", "axis": "x", "from": 270, "to": 350, "hatched": True},
]
GROUPS = [{"id": "entry/e1", "x": 5, "y": 0, "width": 50, "height": 65}]


def problems(nodes=NODES, edges=EDGES, bands=BANDS, rows=ROWS, groups=GROUPS, warnings=None, bundle=BUNDLE):
    snapshots = {r: json.dumps([{"key": k} for k in keys]).encode() for r, keys in rows.items()}
    layout = {"nodes": {n["id"]: [n["x"], n["y"], n["width"], n["height"]] for n in nodes},
              "edges": {e["id"]: {"source": e["source"], "target": e["target"], "points": e["points"]} for e in edges}}
    tile = {"format": "rede.tile/1", "sheet": SHEET, "level": 0, "x": 0, "y": 0, "box": [0, 0, TILE, TILE],
            "nodes": nodes, "edges": edges, "bands": bands, "groups": groups}
    path = f"{SHEET}/0/0_0.json"
    return check_view(SHEET, snapshots, json.dumps(layout).encode(), {path: json.dumps(tile).encode()}, path, TILE, 4, 1, bundle,
                      warnings=warnings)


def with_(items, i, **change):
    out = copy.deepcopy(items)
    out[i].update(change)
    return out


def found(text, **kw):
    out = problems(**kw)
    assert any(text in p for p in out), out


def test_a_relation_line_the_role_reads_no_row_of_is_found():
    found("is no row the role reads", rows=dict(ROWS, period_line=[k for k in ROWS["period_line"] if k[1] != "p2"]))


def test_a_line_that_counts_other_rows_than_the_role_reads_is_found():
    found("says 3 rows", edges=with_(EDGES, 0, rows=3))


def test_a_link_line_without_its_link_row_is_found():
    found("is no row the role reads", rows=dict(ROWS, transfer__from=[]))


def test_a_link_line_of_a_kind_that_is_no_link_kind_is_found():
    """Only a link kind's key reaches from one end to the other: two arrows of a plain kind make no line."""
    found("is no row the role reads", bundle=dict(BUNDLE, unique_keys=[]))
    found("is no row the role reads", edges=[*EDGES, {"id": "entry/e1->posting__account->account/a3", "source": "entry/e1",
                                                      "target": "account/a3", "arrow": "posting__account", "points": []}],
          nodes=[*NODES, {"id": "entry/e1", "x": 400, "y": 10, "width": 40, "height": 20, "status": "valid"}])


def test_a_band_whose_quantity_is_no_sum_of_rows_the_role_reads_is_found():
    found("which is no sum of rows", edges=with_(EDGES, 0, quantity={"slot": "signed", "value": "13"}))
    found("which is no sum of rows", edges=with_(EDGES, 0, quantity={"slot": "period", "value": "4049"}))
    found("which is no sum of rows", rows=dict(ROWS, transfer__amount=[]))
    found("has a width but no quantity", edges=with_(EDGES, 1, width=3))


def test_a_line_whose_rows_reach_an_id_of_another_kind_is_found():
    """A node is its kind and id: a link row or an arrow row whose end has the id of a node of another kind gives
    that node no line (the row is about an account, the node a posting or an entry)."""
    rows = dict(ROWS, posting=[*ROWS["posting"], ["a1"]], entry=[*ROWS["entry"], ["a3"]])
    other = lambda i, kind: {"id": f"{kind}/{i}", "x": 400, "y": 10, "width": 40, "height": 20, "status": "valid"}
    found("is no row the role reads", rows=rows, nodes=[*NODES, other("a1", "posting")],
          edges=[*EDGES, {"id": "posting/a1->transfer__to->account/a2", "source": "posting/a1", "target": "account/a2",
                          "arrow": "transfer__to", "points": []}])
    found("is no row the role reads", rows=rows, nodes=[*NODES, other("a3", "entry")],
          edges=[*EDGES, {"id": "posting/p1->posting__account->entry/a3", "source": "posting/p1", "target": "entry/a3",
                          "arrow": "posting__account", "points": []}])


def test_a_node_above_the_last_level_is_found():
    """A node on a tile above the last level would escape the lane and group checks: such a tile is refused."""
    bad = with_(NODES, 0, group={"relation": "posting__entry", "value": "e9"})
    snapshots = {r: json.dumps([{"key": k} for k in keys]).encode() for r, keys in ROWS.items()}
    layout = {"nodes": {n["id"]: [n["x"], n["y"], n["width"], n["height"]] for n in bad},
              "edges": {e["id"]: {"source": e["source"], "target": e["target"], "points": e["points"]} for e in EDGES}}
    root = {"format": "rede.tile/1", "sheet": SHEET, "level": 0, "x": 0, "y": 0, "box": [0, 0, TILE * 4, TILE * 4],
            "nodes": bad, "edges": EDGES, "clusters": []}
    leaf = {"format": "rede.tile/1", "sheet": SHEET, "level": 1, "x": 0, "y": 0, "box": [0, 0, TILE, TILE],
            "nodes": NODES, "edges": EDGES, "bands": BANDS, "groups": GROUPS}
    data = json.dumps(leaf).encode()
    root["clusters"] = [{"x": 0, "y": 0, "count": 5, "statuses": [{"status": "valid", "count": 5}],
                         "sha256": hashlib.sha256(data).hexdigest()}]
    out = check_view(SHEET, snapshots, json.dumps(layout).encode(),
                     {f"{SHEET}/0/0_0.json": json.dumps(root).encode(), f"{SHEET}/1/0_0.json": data},
                     f"{SHEET}/0/0_0.json", TILE, 4, 2, BUNDLE)
    assert any("above the last level" in p for p in out), out


def test_a_group_that_is_no_cell_the_role_reads_is_found():
    found("stands in a group that is no row", nodes=with_(NODES, 1, group={"relation": "posting__entry", "value": "e2"}))
    found("stands in a group that is no row", nodes=with_(NODES, 1, group={"relation": "transfer__to", "value": "a2"}))


def test_a_box_of_no_member_or_no_element_is_found():
    found("is the group of no node", nodes=[{k: v for k, v in n.items() if k != "group"} for n in NODES])
    found("no element the role reads", groups=[*GROUPS, {"id": "entry/e9", "x": 0, "y": 0, "width": 1, "height": 1}])
    found("has a name that is no rows", groups=[dict(GROUPS[0], name=[{"relation": "account__title", "id": "a1", "value": "Kas"}])])


def test_a_node_outside_its_group_warns():
    warned("lies outside its group", groups=[dict(GROUPS[0], height=30)])


def test_a_lane_that_is_no_cell_the_role_reads_is_found():
    found("stands in a lane that is no row", nodes=with_(NODES, 4, lane={"relation": "account__kind", "value": "equity"}))


def test_a_kind_lane_of_another_kind_is_found():
    found("stands in a lane that is no row", nodes=with_(NODES, 0, lane={"relation": "account"}))


def warned(text, **kw):
    """Layout warns, never blocks (AGENTS.md, rule 5)."""
    out: list[str] = []
    assert problems(warnings=out, **kw) == []
    assert any(text in w for w in out), out


def test_a_node_outside_its_lane_warns():
    warned("lies outside its lane", nodes=with_(NODES, 4, x=100))


def test_lanes_that_cross_warn():
    warned("lanes that cross", bands=[BANDS[0], dict(BANDS[1], to=200), *BANDS[2:]])


def test_a_lane_of_no_node_is_found():
    found("lane of no node", bands=[*BANDS, {"key": "enum:account_kind:equity", "axis": "x", "from": 350, "to": 400}])


def test_a_lane_named_by_rows_the_role_does_not_read_is_found():
    found("has a name that is no rows", bands=[BANDS[0], dict(BANDS[1], name=[{"relation": "account__title", "id": "a1", "value": "Kas"}]), *BANDS[2:]])


def test_a_hatched_lane_that_is_not_unknown_is_found():
    found("is no band", bands=[dict(BANDS[0], hatched=True), *BANDS[1:]])


def test_a_placeholder_in_a_lane_is_found():
    found("shows more than a screened end", nodes=with_(NODES, 2, lane={"unknown": True}))


def test_a_screened_line_from_no_row_is_found():
    found("hangs from no row", rows=dict(ROWS, period_line=[k for k in ROWS["period_line"] if k[1] != "p1"]))


def test_a_sheet_of_lanes_and_relation_lines_the_role_reads_passes():
    out: list[str] = []
    assert problems(warnings=out) == [] and out == []


def test_a_quantity_on_a_line_to_a_stub_an_unknown_or_a_screened_end_is_found():
    """P1 of #216: a line to a placeholder has no rows behind both ends, so it carries no quantity or width; the
    checker refuses one instead of passing it unchecked."""
    q = {"slot": "signed", "value": "999999"}
    found("yet shows a quantity or a width", edges=with_(EDGES, 2, quantity=q))
    found("yet shows a quantity or a width", edges=with_(EDGES, 2, width=999999))
    read = {"posting__entry": {("p1", "e1")}}
    stub = {"id": "posting/p1->posting__entry", "source": "posting/p1", "target": "stub/entry/posting__entry",
            "arrow": "posting__entry", "points": []}
    assert _edge(stub, read, BUNDLE) == []
    assert any("yet shows a quantity" in p for p in _edge(dict(stub, quantity=q), read, BUNDLE))
    unknown = {"id": "posting/p1->posting__account", "source": "posting/p1", "target": "unknown/posting/p1/posting__account",
               "arrow": "unknown_end", "points": []}
    assert _edge(unknown, read, BUNDLE) == []
    assert any("yet shows a quantity" in p for p in _edge(dict(unknown, quantity=q, width=3), read, BUNDLE))


def test_a_count_and_a_sum_from_two_pairs_of_columns_are_found():
    """P1 of #216: the number of rows and the quantity hold in the same pair of columns. Here p1 and a1 stand
    twice as (posting, account), summing 12, and once as (period, posting), summing 100: 2 rows with 100 is
    neither."""
    rows = dict(ROWS, period_line=[*ROWS["period_line"], ["p1", "a1", "x", "100"]])
    assert problems(rows=rows, edges=with_(EDGES, 0, rows=2, quantity={"slot": "signed", "value": "12"})) == []
    found("in the way it counts them", rows=rows, edges=with_(EDGES, 0, rows=2, quantity={"slot": "signed", "value": "100"}))
