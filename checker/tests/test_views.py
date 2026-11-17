"""A published view shows only rows its role reads: nodes, their names, the cells they show, statuses, lines and counts,
every one recomputed from the role's snapshots, at every level (rezono_checker.views). Negative cases first."""

import copy
import hashlib
import json
import pytest

from rezono_checker.views import check_islands, check_page, check_view, island_plan, islands, z_index

SNAPSHOTS = {
    "node": json.dumps([{"key": ["a"]}, {"key": ["b/c"]}]).encode(),
    "node__to": json.dumps([{"key": ["a", "secret"]}, {"key": ["b/c", "a"]}]).encode(),
    "node__label": json.dumps([{"key": ["a", "Alpha"]}]).encode(),
}
# As the compiled bundle names them: kind relations and slot tables. `node__check` is a check: no element.
BUNDLE = {"kinds": [{"id": "node"}], "attributes": [{"table": "node__label"}], "arrows": [{"table": "node__to"}, {"table": "node__from"}]}
TILE, FANOUT, LEVELS = 32, 4, 2
BOXES = {
    "node/a": [0, 0, 10, 10],
    "node/b/c": [20, 0, 10, 10],
    "screened/node/a/node__to": [40, 0, 10, 10],
    "unknown/node/b/c/node__from": [70, 0, 10, 10],
}
PAYLOAD = {
    "node/a": {"status": "valid", "name": [{"relation": "node__label", "id": "a", "value": "Alpha"}],
               "cell": {"relation": "node__label", "state": "known", "value": "Alpha"}},
    "node/b/c": {"status": "valid", "name": [{"relation": "node__label", "id": "a", "value": "Alpha", "via": "node__to"}]},
    "screened/node/a/node__to": {"status": "valid"},
    "unknown/node/b/c/node__from": {"status": "unknown"},
}
LINES = {
    "node/b/c->node__to": {"source": "node/b/c", "target": "node/a", "arrow": "node__to", "points": [[20, 5], [10, 5]]},
    "node/a->node__to": {"source": "node/a", "target": "screened/node/a/node__to", "arrow": "screened", "points": [[10, 5], [40, 5]]},
    "node/b/c->node__from": {"source": "node/b/c", "target": "unknown/node/b/c/node__from", "arrow": "unknown_end", "points": [[30, 5], [70, 5]]},
}


def bytes_of(value) -> bytes:
    return json.dumps(value, sort_keys=True).encode()


def view(boxes=BOXES, payload=PAYLOAD, lines=LINES, counts=None, shown=None, guides=None):
    """A layout, its leaves by centre and a root of clusters, as rezono_publisher.views writes them. `counts`
    overrides the root's clusters; `shown` the lines the tiles show; `guides` the first cluster's guide words."""
    shown = lines if shown is None else shown
    leaves = {}
    for i, (x, y, w, h) in sorted(boxes.items()):
        leaves.setdefault((int((x + w / 2) // TILE), int((y + h / 2) // TILE)), []).append(i)
    pieces, clusters = {}, []
    for (lx, ly), ids in sorted(leaves.items()):
        t = {"format": "rezono.tile/1", "sheet": "map", "level": 1, "x": lx, "y": ly, "box": [lx * TILE, ly * TILE, TILE, TILE],
             "nodes": [{"id": i, "x": boxes[i][0], "y": boxes[i][1], "width": boxes[i][2], "height": boxes[i][3], **payload[i]} for i in ids],
             "edges": [{"id": k, **e} for k, e in sorted(shown.items()) if e["source"] in ids]}
        data = bytes_of(t)
        pieces[f"map/1/{lx}_{ly}.json"] = data
        counted = sorted((z_index(lx, ly), boxes[i][1], boxes[i][0], i) for i in ids if not i.startswith(("unknown/", "screened/", "stub/")))
        n = len(counted)

        def end(i):
            return {"id": i, **({"name": payload[i]["name"]} if "name" in payload[i] else {})}

        clusters.append({"x": lx, "y": ly, "box": [0, 0, 1, 1], "count": n,
                         "statuses": [{"status": "valid", "count": n}] if n else [], "sha256": hashlib.sha256(data).hexdigest(),
                         **({"first": end(counted[0][3]), "last": end(counted[-1][3])} if counted else {})})
    if counts:
        for c, (n, statuses) in zip(clusters, counts):
            c["count"], c["statuses"] = n, statuses
    if guides:
        clusters[0].update(guides)
    pieces["map/0/0_0.json"] = bytes_of({"format": "rezono.tile/1", "sheet": "map", "level": 0, "x": 0, "y": 0, "box": [0, 0, 128, 128], "clusters": clusters})
    layout = {"nodes": boxes, "edges": {k: {"source": e["source"], "target": e["target"], "points": e["points"]} for k, e in lines.items()}}
    return bytes_of(layout), pieces


def problems(layout, tiles, snapshots=SNAPSHOTS, bundle=BUNDLE, stubs=None):
    return check_view("map", snapshots, layout, tiles, "map/0/0_0.json", TILE, FANOUT, LEVELS, bundle, stubs)


STUB = "stub/other/node__to"
STUB_SHOWS = {"island": "other", "path": ["other"], "arrow": "node__to", "count": 1}


def stub_view(shows=STUB_SHOWS, line="node/b/c->node__to"):
    """The line from b/c to a ends at a stub, as if a were on another island's Map; `line` is its id."""
    lines = LINES | {line: {"source": "node/b/c", "target": STUB, "arrow": "node__to", "points": [[30, 5], [100, 5]]}}
    return view(BOXES | {STUB: [100, 0, 10, 10]}, PAYLOAD | {STUB: {"status": "valid", "stub": shows}}, lines)


def test_a_stub_shows_what_the_island_levels_give_it():
    assert problems(*stub_view(), stubs={STUB: STUB_SHOWS}) == []
    assert any("a stub the island levels do not give" in p for p in problems(*stub_view()))
    got = problems(*stub_view(STUB_SHOWS | {"count": 2}), stubs={STUB: STUB_SHOWS})
    assert any(f"stub {STUB} shows" in p for p in got), got
    got = problems(*stub_view(STUB_SHOWS | {"path": ["elsewhere"]}), stubs={STUB: STUB_SHOWS})
    assert any(f"stub {STUB} shows" in p for p in got), got


def test_a_line_to_a_stub_is_named_by_its_source_and_arrow_and_by_its_stub_when_the_arrow_is_multivalued():
    """docs/gui.md (Zoom: islands by meaning): `source->arrow` for a single-valued arrow, `source->arrow->stub`
    for a multivalued one, whose lines from one source can end at stubs of several islands."""
    many = BUNDLE | {"arrows": [{"table": "node__to", "multivalued": True}, {"table": "node__from"}]}
    long = f"node/b/c->node__to->{STUB}"
    assert problems(*stub_view(line=long), bundle=many, stubs={STUB: STUB_SHOWS}) == []
    got = problems(*stub_view(), bundle=many, stubs={STUB: STUB_SHOWS})
    assert any("line node/b/c->node__to is not named by its source and arrow" in p for p in got), got
    got = problems(*stub_view(line=long), stubs={STUB: STUB_SHOWS})
    assert any(f"line {long} is not named by its source and arrow" in p for p in got), got


# `leaf` is a subkind of `node`: its element `a` is in both tables, and is one element, a leaf.
SUB = BUNDLE | {"kinds": [{"id": "node"}, {"id": "leaf", "parent": "node"}]}
WITH_LEAF = SNAPSHOTS | {"leaf": json.dumps([{"key": ["a"]}]).encode()}


def test_an_element_of_a_subkind_drawn_at_its_supertype_is_found():
    got = problems(*view(), snapshots=WITH_LEAF, bundle=SUB)
    assert any("node/a is not its element at its most specific kind" in p for p in got), got


def test_an_element_of_a_subkind_is_drawn_once_with_its_supertypes_arrows():
    """leaf/a has the arrow node__to of its supertype; node/b/c points to it as a leaf."""
    boxes = {("leaf/a" if k == "node/a" else k.replace("node/a/", "leaf/a/")): v for k, v in BOXES.items()}
    payload = {("leaf/a" if k == "node/a" else k.replace("node/a/", "leaf/a/")): v for k, v in PAYLOAD.items()}
    lines = {
        "node/b/c->node__to": LINES["node/b/c->node__to"] | {"target": "leaf/a"},
        "leaf/a->node__to": LINES["node/a->node__to"] | {"source": "leaf/a", "target": "screened/leaf/a/node__to"},
        "node/b/c->node__from": LINES["node/b/c->node__from"],
    }
    assert problems(*view(boxes, payload, lines), snapshots=WITH_LEAF, bundle=SUB) == []


def found(text, layout, tiles):
    got = problems(layout, tiles)
    assert any(text in p for p in got), got


def test_a_node_the_role_does_not_read_is_found():
    found("node/secret", *view(BOXES | {"node/secret": [100, 0, 10, 10]}, PAYLOAD | {"node/secret": {"status": "valid"}}))


def test_a_placeholder_hanging_from_a_row_the_role_does_not_read_is_found():
    found("screened/node/secret", *view(BOXES | {"screened/node/secret/node__to": [100, 0, 10, 10]},
                                        PAYLOAD | {"screened/node/secret/node__to": {"status": "valid"}}))


def test_an_invented_line_between_readable_nodes_is_found():
    found("is no row the role reads", *view(lines=LINES | {"node/a->node__x": {"source": "node/a", "target": "node/b/c", "arrow": "node__x", "points": [[0, 0], [1, 1]]}}))


def test_a_line_the_tile_shows_with_other_ends_is_found():
    moved = copy.deepcopy(LINES)
    moved["node/b/c->node__to"]["target"] = "node/b/c"
    found("not as laid out", *view(shown=moved))


def test_a_screened_line_from_no_arrow_row_is_found():
    lines = LINES | {"node/b/c->node__x": {"source": "node/b/c", "target": "screened/node/b/c/node__x", "arrow": "screened", "points": [[0, 0], [1, 1]]}}
    found("hangs from no row", *view(BOXES | {"screened/node/b/c/node__x": [100, 0, 10, 10]},
                                           PAYLOAD | {"screened/node/b/c/node__x": {"status": "valid"}}, lines))


def test_a_cell_that_is_no_row_is_found():
    found("shows a cell", *view(payload=PAYLOAD | {"node/a": {"status": "valid", "cell": {"relation": "node__label", "state": "known", "value": "Beta"}}}))


AMOUNT = {"relation": "node__amount", "state": "known", "minor_units": "690000", "currency": "EUR"}
AMOUNT_BUNDLE = BUNDLE | {"attributes": [*BUNDLE["attributes"],
    {"id": "node.amount", "table": "node__amount", "kind": "node", "type": "integer", "currency": "EUR"}]}
AMOUNT_SNAPSHOTS = SNAPSHOTS | {"node__amount": bytes_of([
    {"key": ["a", "690000"]}, {"key": ["b/c", "9007199254740993"]}])}


def test_amount_cell_is_checked_against_its_own_readable_row_and_bundle_currency():
    for node, value in [("node/a", "690000"), ("node/b/c", "9007199254740993")]:
        payload = PAYLOAD | {node: {"status": "valid", "cell": AMOUNT | {"minor_units": value}}}
        assert problems(*view(payload=payload), snapshots=AMOUNT_SNAPSHOTS, bundle=AMOUNT_BUNDLE) == []


@pytest.mark.parametrize("cell", [
    AMOUNT | {"currency": "USD"}, AMOUNT | {"minor_units": "9007199254740993"},
    AMOUNT | {"minor_units": 690000}, AMOUNT | {"minor_units": "0690000"},
    AMOUNT | {"minor_units": "690000.0"}, AMOUNT | {"value": "690000"},
    AMOUNT | {"state": "unknown"}, AMOUNT | {"secret": "unread"},
    {"relation": "node__amount", "state": "known", "value": "690000"},
    AMOUNT | {"relation": "node__label"},
])
def test_amount_cell_cannot_forge_value_currency_type_or_extra_fields(cell):
    got = problems(*view(payload=PAYLOAD | {"node/a": {"status": "valid", "cell": cell}}),
                   snapshots=AMOUNT_SNAPSHOTS, bundle=AMOUNT_BUNDLE)
    assert any("shows a cell" in p for p in got), got


def test_amount_cell_stays_hidden_without_its_snapshot():
    got = problems(*view(payload=PAYLOAD | {"node/a": {"status": "valid", "cell": AMOUNT}}),
                   bundle=AMOUNT_BUNDLE)
    assert any("shows a cell" in p for p in got), got


def test_an_invented_status_is_found():
    found("has status", *view(payload=PAYLOAD | {"node/b/c": {"status": "violated"}}))


def test_text_in_a_tile_is_found():
    found("holds more", *view(payload=PAYLOAD | {"node/b/c": {"status": "valid", "lines": ["Geheim"]}}))


def test_counts_moved_between_clusters_are_found():
    found("counts", *view(counts=[(1, [{"status": "valid", "count": 1}]), (1, [{"status": "valid", "count": 1}])]))


def test_guide_words_are_the_first_and_last_in_reading_order():
    layout, tiles = view()
    root = json.loads(tiles["map/0/0_0.json"])
    assert [(c["first"]["id"], c["last"]["id"]) for c in root["clusters"] if c["count"]] == [("node/a", "node/b/c")]
    assert all("first" not in c for c in root["clusters"] if not c["count"])
    assert problems(layout, tiles) == []


def test_a_guide_word_out_of_reading_order_is_found():
    layout, tiles = view()
    last = json.loads(tiles["map/0/0_0.json"])["clusters"][0]["last"]
    found("as its first element", *view(guides={"first": last}))


def test_a_guide_word_name_that_is_no_row_is_found():
    layout, tiles = view()
    first = json.loads(tiles["map/0/0_0.json"])["clusters"][0]["first"]
    found("shows a name", *view(guides={"first": {**first, "name": [{"relation": "node__label", "id": first["id"].partition("/")[2], "value": "Geheim"}]}}))


def test_the_z_curve_runs_through_every_aligned_block():
    assert sorted(z_index(x, y) for x in range(4) for y in range(4)) == list(range(16))
    assert [z_index(1, 0), z_index(0, 1), z_index(2, 0), z_index(4, 0)] == [1, 2, 4, 16]


def test_a_node_its_tile_does_not_draw_is_found():
    """Counts and layout agree, but the leaf tile leaves the node out: the view counts what it does not draw."""
    layout, tiles = view(payload=PAYLOAD)
    leaf = json.loads(tiles["map/1/0_0.json"])
    leaf["nodes"] = [n for n in leaf["nodes"] if n["id"] != "node/b/c"]
    tiles["map/1/0_0.json"] = bytes_of(leaf)
    root = json.loads(tiles["map/0/0_0.json"])
    root["clusters"][0]["sha256"] = hashlib.sha256(tiles["map/1/0_0.json"]).hexdigest()
    tiles["map/0/0_0.json"] = bytes_of(root)
    found("node/b/c is drawn in no tile", layout, tiles)


def test_an_invented_status_count_is_found():
    found("counts", *view(counts=[(2, [{"status": "violated", "count": 2}])]))


def test_a_replaced_tile_is_found():
    layout, tiles = view()
    tiles["map/1/1_0.json"] = tiles["map/1/1_0.json"] + b" "
    found("sha256", layout, tiles)


def test_a_tile_no_parent_names_is_found():
    layout, tiles = view()
    tiles["map/1/3_0.json"] = tiles["map/1/0_0.json"]
    found("not reached", layout, tiles)


def test_a_cell_of_another_row_is_found():
    found("shows a cell", *view(payload=PAYLOAD | {"node/b/c": {"status": "valid", "cell": {"relation": "node__label", "state": "known", "value": "Alpha"}}}))


def test_a_name_that_is_no_row_is_found():
    found("shows a name", *view(payload=PAYLOAD | {"node/a": {"status": "valid", "name": [{"relation": "node__label", "id": "a", "value": "Beta"}]}}))


def test_a_name_of_another_row_is_found():
    """Its own name names only the row itself; another row's name needs an arrow row that reaches it."""
    found("shows a name", *view(payload=PAYLOAD | {"node/b/c": {"status": "valid", "name": [{"relation": "node__label", "id": "a", "value": "Alpha"}]}}))


def test_a_name_through_an_arrow_that_does_not_reach_it_is_found():
    found("shows a name", *view(payload=PAYLOAD | {"node/b/c": {"status": "valid", "name": [{"id": "secret", "via": "node__to"}]}}))


def test_a_named_placeholder_is_found():
    found("more than a screened end", *view(payload=PAYLOAD | {"screened/node/a/node__to": {"status": "valid", "name": [{"id": "secret", "via": "node__to"}]}}))


def test_a_view_of_readable_rows_passes():
    """Ids may hold a slash; an unknown end and a screened arrow hang from rows the role reads."""
    assert problems(*view()) == []


def test_a_row_is_read_through_its_kind_or_one_of_its_slots():
    """Without the kind relation, node/a and node/b/c are still read through their slot node__to."""
    only = {k: SNAPSHOTS[k] for k in ("node__to", "node__label")}
    assert problems(*view(), snapshots=only) == []
    found_ = problems(*view(), snapshots={"node__label": SNAPSHOTS["node__label"]})
    assert any("node/b/c " in p for p in found_) and not any("node/a " in p for p in found_), found_


def page(kinds):
    return json.dumps({"format": "rezono.page/2", "title": "t", "kinds": kinds, "sheets": ["map"]}).encode()


ALPHA = [{"relation": "node__label", "id": "a", "value": "Alpha"}]


def test_a_check_relation_is_no_element():
    """Counted as the viewer counts: a relation the bundle names as no kind or slot holds no element."""
    with_check = SNAPSHOTS | {"node__check": json.dumps([{"key": ["zz"]}]).encode()}
    assert check_page(with_check, BUNDLE, page([{"kind": "node", "count": 2, "first": [{"id": "a"}, {"id": "b/c"}]}])) == []


def test_a_page_index_that_lists_or_counts_more_than_the_role_reads_is_found():
    assert check_page(SNAPSHOTS, BUNDLE, page([{"kind": "node", "count": 2, "first": [{"id": "a", "name": ALPHA}, {"id": "b/c"}]}])) == []
    assert any("node/secret" in p for p in check_page(SNAPSHOTS, BUNDLE, page([{"kind": "node", "count": 2, "first": [{"id": "a"}, {"id": "secret"}]}])))
    assert any("counts 3" in p for p in check_page(SNAPSHOTS, BUNDLE, page([{"kind": "node", "count": 3, "first": [{"id": "a"}]}])))
    assert any("counts 1" in p for p in check_page(SNAPSHOTS, BUNDLE, page([{"kind": "node", "count": 1, "first": [{"id": "a"}]}]))), "a low count is a wrong page"


def test_a_page_index_counts_an_element_once_at_its_most_specific_kind():
    kinds = [{"kind": "node", "count": 1, "first": [{"id": "b/c"}]}, {"kind": "leaf", "count": 1, "first": [{"id": "a"}]}]
    assert check_page(WITH_LEAF, SUB, page(kinds)) == []
    twice = [{"kind": "node", "count": 2, "first": [{"id": "a"}, {"id": "b/c"}]}, {"kind": "leaf", "count": 1, "first": [{"id": "a"}]}]
    assert any("counts 2" in p for p in check_page(WITH_LEAF, SUB, page(twice)))


def test_a_page_index_that_names_a_row_by_rows_the_role_does_not_read_is_found():
    wrong = [{"relation": "node__label", "id": "a", "value": "Beta"}]
    assert any("has a name" in p for p in check_page(SNAPSHOTS, BUNDLE, page([{"kind": "node", "count": 1, "first": [{"id": "a", "name": wrong}]}])))
    other = [{"relation": "node__label", "id": "a", "value": "Alpha"}]
    assert any("has a name" in p for p in check_page(SNAPSHOTS, BUNDLE, page([{"kind": "node", "count": 2, "first": [{"id": "b/c", "name": other}]}])))


# The overview by meaning: the same kind tree and rows as the viewer's islands.test.ts, so both give one answer.
TREE = {"kinds": [{"id": "k"}, {"id": "sub", "parent": "k"}, {"id": "link"}],
        "arrows": [{"table": "k__to", "kind": "k", "target": "k"}, {"table": "link__end", "kind": "link", "target": "k"}]}
ROWS = {
    "k": json.dumps([{"key": ["a"]}, {"key": ["b"]}]).encode(),
    "sub": json.dumps([{"key": ["a"]}]).encode(),
    "k__to": json.dumps([{"key": ["a", "b"]}]).encode(),
    "link": json.dumps([{"key": ["l"]}]).encode(),
    "link__end": json.dumps([{"key": ["l", "a"]}]).encode(),
}


def valid(n):
    return [{"status": "valid", "count": n}]


def made(rows=ROWS, tree=TREE):
    """The levels and Map layouts as the publisher writes them, from the recount itself."""
    plan = island_plan(rows, tree)
    levels = {k: bytes_of(v) for k, v in plan.levels.items()}
    layouts = {sheet: bytes_of({"nodes": {i: [0, 0, 1, 1] for i in sorted(ids | set(plan.stubs[sheet]))},
                                "edges": {line: {"source": source, "target": stub, "points": []} for line, source, stub in sorted(plan.stub_lines[sheet])}})
               for sheet, ids in plan.maps.items()}
    return levels, layouts


def test_islands_follow_the_kind_tree_and_bundle_the_lines_between_them():
    want, maps = islands(ROWS, TREE)
    assert sorted(want) == ["k.k", "root"]
    assert want["root"]["islands"] == [
        {"key": "k.k", "kind": "k", "count": 2, "statuses": valid(2), "opens": {"level": "k.k"}},
        {"key": "k.link", "kind": "link", "count": 1, "statuses": valid(1), "opens": {"map": "map.k.link"}},
    ]
    assert want["root"]["lines"] == [{"from": "k.link", "to": "k.k", "arrow": "link__end", "count": 1}]
    assert [(i["key"], i["opens"]) for i in want["k.k"]["islands"]] == [("k.sub", {"map": "map.k.sub"}), ("o.k", {"map": "map.o.k"})]
    assert want["k.k"]["lines"] == [{"from": "k.sub", "to": "o.k", "arrow": "k__to", "count": 1}]
    assert maps == {"map.k.sub": {"sub/a"}, "map.o.k": {"k/b"}, "map.k.link": {"link/l"}}
    assert check_islands(ROWS, TREE, *made()) == []


def test_a_level_of_one_island_is_skipped_and_a_single_root_island_opens_at_once():
    rows = {k: v for k, v in ROWS.items() if k not in ("link", "link__end")}
    want, _ = islands(rows, TREE)
    assert sorted(want) == ["root"] and [i["key"] for i in want["root"]["islands"]] == ["k.sub", "o.k"]
    only = {"k": json.dumps([{"key": ["a"]}]).encode(), "sub": json.dumps([{"key": ["a"]}]).encode(), "link": ROWS["link"]}
    want, _ = islands(only, TREE)
    assert [i["key"] for i in want["root"]["islands"]] == ["k.sub", "k.link"]


def test_a_single_root_island_that_opens_a_map_is_the_sheet_map():
    """As islands.test.ts: one kind with elements, no subkinds that hold any, so no level 0: the page opens on
    that island's Map, the sheet `map`."""
    rows = {"k": ROWS["k"]}
    want, maps = islands(rows, TREE)
    assert want == {} and maps == {"map": {"k/a", "k/b"}}
    levels = {k: bytes_of(v) for k, v in want.items()}
    layouts = {"map": bytes_of({"nodes": {"k/a": [0, 0, 1, 1], "k/b": [0, 0, 1, 1]}, "edges": {}})}
    assert check_islands(rows, TREE, levels, layouts) == []


def test_an_island_that_counts_or_bundles_other_than_the_rows_is_found():
    levels, layouts = made()
    for change in (
        lambda r: r["islands"][0].update(count=3),
        lambda r: r["islands"][0].update(statuses=valid(1) + [{"status": "unknown", "count": 1}]),
        lambda r: r["lines"][0].update(count=2),
        lambda r: r["lines"].append({"from": "k.k", "to": "k.link", "arrow": "k__to", "count": 1}),
        lambda r: r["islands"].pop(),
    ):
        root = json.loads(levels["root"])
        change(root)
        got = check_islands(ROWS, TREE, levels | {"root": bytes_of(root)}, layouts)
        assert any("level root is not what the role's rows give" in p for p in got), got


def test_a_missing_or_invented_level_or_map_is_found():
    levels, layouts = made()
    assert any("level k.k is missing" in p for p in check_islands(ROWS, TREE, {"root": levels["root"]}, layouts))
    assert any("level k.x is no level" in p for p in check_islands(ROWS, TREE, levels | {"k.x": levels["root"]}, layouts))
    assert any("map.k.sub is missing" in p for p in check_islands(ROWS, TREE, levels, {k: v for k, v in layouts.items() if k != "map.k.sub"}))
    assert any("map of no island" in p.lower() for p in check_islands(ROWS, TREE, levels, layouts | {"map": layouts["map.k.sub"]}))


def test_a_map_that_draws_another_island_s_element_is_found():
    levels, layouts = made()
    other = bytes_of({"nodes": {"sub/a": [0, 0, 1, 1], "k/b": [2, 0, 1, 1], "unknown/sub/a/k__to": [4, 0, 1, 1]}, "edges": {}})
    got = check_islands(ROWS, TREE, levels, layouts | {"map.k.sub": other})
    assert any("map.k.sub draws 2 elements, the island holds 1" in p for p in got), got


def test_a_line_to_another_island_ends_at_a_stub_that_opens_it():
    """On a Map laid out as an index (no line between two of its elements), one stub per element below it;
    the stub names the island and its path of steps from level 0. A line that comes in from another island
    starts at a stub of its own (`direction: in`), below the element it ends at."""
    plan = island_plan(ROWS, TREE)
    assert plan.stubs == {
        "map.k.sub": {
            "stub/sub/a/o.k/k__to": {"island": "o.k", "path": ["k.k", "o.k"], "arrow": "k__to", "count": 1},
            "stub/in/sub/a/k.link/link__end": {"island": "k.link", "path": ["k.link"], "arrow": "link__end", "count": 1, "direction": "in"},
        },
        "map.o.k": {"stub/in/k/b/k.sub/k__to": {"island": "k.sub", "path": ["k.k", "k.sub"], "arrow": "k__to", "count": 1, "direction": "in"}},
        "map.k.link": {"stub/link/l/k.sub/link__end": {"island": "k.sub", "path": ["k.k", "k.sub"], "arrow": "link__end", "count": 1}},
    }
    assert plan.stub_lines["map.k.link"] == {("link/l->link__end", "link/l", "stub/link/l/k.sub/link__end")}
    assert plan.stub_lines["map.o.k"] == {("stub/in/k/b/k.sub/k__to->k__to->k/b", "stub/in/k/b/k.sub/k__to", "k/b")}


def test_on_a_map_with_lines_one_stub_per_island_and_arrow_counts_its_lines():
    """As islands.test.ts: a, c and d are of the subkind, a → c inside, c → b and d → b to the kind's own."""
    rows = {"k": json.dumps([{"key": [i]} for i in "abcd"]).encode(), "sub": json.dumps([{"key": [i]} for i in "acd"]).encode(),
            "k__to": json.dumps([{"key": ["a", "c"]}, {"key": ["c", "b"]}, {"key": ["d", "b"]}]).encode()}
    plan = island_plan(rows, TREE)
    assert plan.stubs["map.k.sub"] == {"stub/o.k/k__to": {"island": "o.k", "path": ["o.k"], "arrow": "k__to", "count": 2}}
    assert check_islands(rows, TREE, *made(rows)) == []


# A multivalued arrow across islands: `src` elements point by `src__to` into both subkinds of `t`, so one
# source has lines to the stubs of two islands; `src__next` keeps the source's Map from being an index.
SPREAD = {"kinds": [{"id": "src"}, {"id": "t"}, {"id": "one", "parent": "t"}, {"id": "two", "parent": "t"}],
          "arrows": [{"table": "src__to", "kind": "src", "target": "t", "multivalued": True},
                     {"table": "src__next", "kind": "src", "target": "src"}]}
SPREAD_ROWS = {
    "src": json.dumps([{"key": ["p"]}, {"key": ["q"]}]).encode(),
    "t": json.dumps([{"key": ["x"]}, {"key": ["y"]}, {"key": ["z"]}]).encode(),
    "one": json.dumps([{"key": ["x"]}, {"key": ["z"]}]).encode(),
    "two": json.dumps([{"key": ["y"]}]).encode(),
    "src__next": json.dumps([{"key": ["p", "q"]}]).encode(),
    "src__to": json.dumps([{"key": ["p", "x"]}, {"key": ["p", "y"]}, {"key": ["q", "x"]}, {"key": ["q", "z"]}]).encode(),
}


def test_the_lines_of_a_multivalued_arrow_to_stubs_of_several_islands_are_named_by_their_stubs():
    """p reaches both islands of t through one arrow: two lines, each named by its stub (docs/gui.md). q reaches
    two elements of one island: one line, its stub counting both rows. The short name would make p's two lines
    one, and a Map drawing it is refused."""
    plan = island_plan(SPREAD_ROWS, SPREAD)
    assert plan.stubs["map.k.src"] == {
        "stub/k.one/src__to": {"island": "k.one", "path": ["k.t", "k.one"], "arrow": "src__to", "count": 3},
        "stub/k.two/src__to": {"island": "k.two", "path": ["k.t", "k.two"], "arrow": "src__to", "count": 1},
    }
    assert plan.stub_lines["map.k.src"] == {
        ("src/p->src__to->stub/k.one/src__to", "src/p", "stub/k.one/src__to"),
        ("src/p->src__to->stub/k.two/src__to", "src/p", "stub/k.two/src__to"),
        ("src/q->src__to->stub/k.one/src__to", "src/q", "stub/k.one/src__to"),
    }
    levels, layouts = made(SPREAD_ROWS, SPREAD)
    assert check_islands(SPREAD_ROWS, SPREAD, levels, layouts) == []
    whole = json.loads(layouts["map.k.src"])
    whole["edges"] = {line.rsplit("->", 1)[0] if line.startswith("src/") else line: e for line, e in whole["edges"].items()}
    got = check_islands(SPREAD_ROWS, SPREAD, levels, layouts | {"map.k.src": bytes_of(whole)})
    assert any("map.k.src draws 2 lines to stubs, its lines to other islands are 3" in p for p in got), got


def test_a_map_without_its_stubs_or_with_other_lines_to_them_is_found():
    levels, layouts = made()
    bare = bytes_of({"nodes": {"sub/a": [0, 0, 1, 1]}, "edges": {}})
    got = check_islands(ROWS, TREE, levels, layouts | {"map.k.sub": bare})
    assert any("map.k.sub does not have the stubs" in p for p in got), got
    stub = "stub/sub/a/o.k/k__to"
    unlinked = bytes_of({"nodes": {"sub/a": [0, 0, 1, 1], stub: [0, 2, 1, 1]}, "edges": {}})
    got = check_islands(ROWS, TREE, levels, layouts | {"map.k.sub": unlinked})
    assert any("map.k.sub draws 0 lines to stubs" in p for p in got), got
