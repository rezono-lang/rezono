"""A Matrix sheet (`matrix.<id>`) is checked like any sheet (rezono_checker.views, check_view), plus its binding in
the compiled bundle: every node is a head named by its axis and the element it shows (`rows/<of>`,
`columns/<of>`), which the role must read at its most specific kind and which is of its axis's kind; every cell
runs from a row's head to a column's head, is of the binding's sign and, for a relation, names exactly its `from`
and `to` columns, so it is the rows the role reads in that direction. Only a Matrix has nodes with `of`.
Negative cases first."""

import copy
import json

from rezono_checker.views import check_view

MATRIX = {"id": "zones", "title_message": "m", "rows": {"kind": "zone"}, "columns": {"kind": "zone"},
          "cells": {"relation": "zone_crossing", "from": "za", "to": "zb", "from_kinds": ["zone"], "to_kinds": ["zone"]}}
BUNDLE = {
    "kinds": [{"id": "zone"}, {"id": "site"}],
    "attributes": [{"table": "zone__title"}],
    "arrows": [{"id": "zone.next", "table": "zone__next", "kind": "zone", "target": "zone"}],
    "relations": [{"id": "zone_crossing", "columns": [{"name": "za", "type": "string"}, {"name": "zb", "type": "string"}]}],
    "channels": {"matrices": [MATRIX, dict(MATRIX, id="next", cells={"arrow": "zone.next"})]},
}
# z1 -> z2 is a crossing; z2 -> z1 is not. A site s1 has the id of no zone.
ROWS = {"zone": [["z1"], ["z2"]], "site": [["s1"]], "zone__title": [["z1", "Noord"]],
        "zone_crossing": [["z1", "z2"], ["z2", "z2"]], "zone__next": [["z1", "z2"]]}
SHEET, TILE = "matrix.zones", 512
# Each zone heads a row (spanning it) and a column (spanning it).
NODES = [
    {"id": "rows/zone/z1", "of": "zone/z1", "x": 0, "y": 40, "width": 120, "height": 40, "status": "valid"},
    {"id": "rows/zone/z2", "of": "zone/z2", "x": 0, "y": 80, "width": 120, "height": 40, "status": "valid"},
    {"id": "columns/zone/z1", "of": "zone/z1", "x": 40, "y": 0, "width": 40, "height": 120, "status": "valid"},
    {"id": "columns/zone/z2", "of": "zone/z2", "x": 80, "y": 0, "width": 40, "height": 120, "status": "valid"},
]
CELL = lambda r, c, sign="zone_crossing", **kw: {
    "id": f"rows/zone/{r}->{sign}->columns/zone/{c}", "source": f"rows/zone/{r}", "target": f"columns/zone/{c}",
    "arrow": sign, "points": [[80, 60], [120, 60]], **({"columns": ["za", "zb"]} if sign == "zone_crossing" else {}), **kw}
EDGES = [CELL("z1", "z2"), CELL("z2", "z2")]


def problems(nodes=NODES, edges=EDGES, rows=ROWS, of=None, sheet=SHEET, bundle=BUNDLE, warnings=None):
    snapshots = {r: json.dumps([{"key": k} for k in keys]).encode() for r, keys in rows.items()}
    layout = {"nodes": {n["id"]: [n["x"], n["y"], n["width"], n["height"]] for n in nodes},
              "edges": {e["id"]: {"source": e["source"], "target": e["target"], "points": e["points"]} for e in edges},
              "of": of if of is not None else {n["id"]: n["of"] for n in nodes if "of" in n}}
    tile = {"format": "rezono.tile/1", "sheet": sheet, "level": 0, "x": 0, "y": 0, "box": [0, 0, TILE, TILE],
            "nodes": nodes, "edges": edges}
    path = f"{sheet}/0/0_0.json"
    return check_view(sheet, snapshots, json.dumps(layout).encode(), {path: json.dumps(tile).encode()}, path, TILE, 4, 1, bundle,
                      warnings=warnings)


def changed(items, i, **change):
    out = copy.deepcopy(items)
    out[i].update(change)
    return out


def found(text, **kw):
    out = problems(**kw)
    assert any(text in p for p in out), out


def test_a_cell_turned_round_with_its_columns_is_found():
    """P1 of #237: rows/z2 -> columns/z1 with columns [zb, za] is the row (z1, z2) read backwards. As rows it holds;
    the binding says from is za and to is zb, so it is refused."""
    found("is not of the Matrix's source", edges=[*EDGES, CELL("z2", "z1", columns=["zb", "za"])])


def test_a_cell_of_another_sign_or_without_its_columns_is_found():
    found("is not of the Matrix's source", edges=[CELL("z1", "z2", sign="zone__next"), CELL("z2", "z2")])
    found("is not of the Matrix's source", edges=[CELL("z1", "z2", columns=None), CELL("z2", "z2")])


def test_a_cell_from_a_column_to_a_row_is_found():
    flipped = {"id": "columns/zone/z2->zone_crossing->rows/zone/z1", "source": "columns/zone/z2", "target": "rows/zone/z1",
               "arrow": "zone_crossing", "points": [], "columns": ["za", "zb"]}
    found("is no cell from a row's head to a column's head", edges=[*EDGES, flipped])


def test_a_head_whose_id_is_not_its_axis_and_element_is_found():
    """P1 of #237: a page shows a node's id, so the id is the element it shows: a head `rows/zone/z2` that says it
    shows z1, or a node named after nothing, is refused."""
    found("is no head rows/<element>", nodes=changed(NODES, 1, of="zone/z1"))
    other = changed(NODES, 1, id="zone/hidden")
    found("is no head", nodes=other, edges=[EDGES[0]])


def test_a_head_of_an_element_of_another_kind_is_found():
    nodes = [*NODES, {"id": "rows/site/s1", "of": "site/s1", "x": 0, "y": 120, "width": 120, "height": 40, "status": "valid"}]
    found("of an element of its axis kind", nodes=nodes)


def test_nodes_that_show_other_elements_on_a_sheet_that_is_no_matrix_are_found():
    """P1 of #237: on a Flow a node `zone/hidden` that says it shows `zone/z1` would put a hidden id on the page."""
    nodes = [{"id": "zone/hidden", "of": "zone/z1", "x": 0, "y": 0, "width": 40, "height": 40, "status": "valid"}]
    found("only a Matrix has such nodes", nodes=nodes, edges=[], sheet="flow.zones")
    found("no Matrix of the bundle has this sheet", sheet="matrix.nothing")


def test_a_head_of_an_element_the_role_does_not_read_is_found():
    found("rows/zone/z2 is no row the role reads", nodes=changed(NODES, 1, of="zone/secret"))


def test_a_tile_that_shows_another_element_than_the_layout_is_found():
    found("as another element than the layout", of={n["id"]: n["of"] for n in NODES} | {"rows/zone/z2": "zone/z1"})


def test_a_layout_that_says_a_placeholder_or_no_node_shows_an_element_is_found():
    found("it is no node", of={n["id"]: n["of"] for n in NODES} | {"rows/zone/z9": "zone/z1"})


def test_a_cell_that_is_no_row_between_its_elements_is_found():
    found("is no row the role reads", edges=[CELL("z2", "z1")])


def test_a_cell_named_by_its_elements_rather_than_its_ends_is_found():
    found("not named by its ends", edges=changed(EDGES, 0, id="zone/z1->zone_crossing->zone/z2"))


def test_a_cell_that_counts_more_rows_than_the_role_reads_is_found():
    found("says 2 rows", edges=changed(EDGES, 0, rows=2))


def test_an_arrow_matrix_holds_in_its_direction_without_columns():
    edges = [CELL("z1", "z2", sign="zone__next")]
    assert problems(edges=edges, sheet="matrix.next") == []
    found("is no row the role reads", edges=[CELL("z2", "z1", sign="zone__next")], sheet="matrix.next")


def test_heads_and_cells_the_role_reads_pass():
    assert problems() == []


def test_a_head_stands_in_the_lane_of_the_element_it_shows():
    """A Board (docs/gui.md): a column's head holds the cell of its element's row that puts it in its column. The
    checker reads that cell by the element the head shows, never by the head's own id, and a tile's band is the
    lane of such a head. A lane value the role does not read is found."""
    bundle = dict(BUNDLE, attributes=[*BUNDLE["attributes"], {"table": "zone__state", "enum": "State"}])
    rows = dict(ROWS, zone__state=[["z1", "open"]])
    laned = changed(changed(NODES, 2, lane={"relation": "zone__state", "value": "open"}), 3, lane={"unknown": True})
    warnings: list[str] = []
    assert problems(nodes=laned, rows=rows, bundle=bundle, warnings=warnings) == []
    # The lanes are the columns: that a row's head stands in none is no warning; a column's head without one is.
    assert not any("others in none" in w for w in warnings), warnings
    problems(nodes=changed(NODES, 2, lane={"relation": "zone__state", "value": "open"}), rows=rows, bundle=bundle, warnings=warnings)
    assert any("others in none" in w for w in warnings), warnings
    found("stands in a lane that is no row the role reads", nodes=laned, rows=ROWS, bundle=bundle)
    found("stands in a lane that is no row the role reads",
          nodes=changed(laned, 3, lane={"relation": "zone__state", "value": "open"}), rows=rows, bundle=bundle)
