"""Hand-placed boxes and exact counts, independent of the renderer and containment helper."""

import copy
from dataclasses import asdict
import hashlib
import json

import pytest

from rezono_checker.semiotic import Outside, containment
from rezono_checker.views import Role


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def fixture(*, second_x=20, group_width=64, group=True, lane=True, tiled=False, repeated=False):
    bundle = {"kinds": [{"id": "node"}, {"id": "group"}], "attributes": [],
              "arrows": [{"id": "node.group", "table": "node__group", "kind": "node", "target": "group"}]}
    snapshots = {"node": encoded([{"key": ["a"]}, {"key": ["b"]}]),
                 "group": encoded([{"key": ["g"]}]),
                 "node__group": encoded([{"key": ["a", "g"]}, {"key": ["b", "g"]}])}
    nodes = [{"id": "node/a", "x": 0, "y": 0, "width": 10, "height": 10, "status": "valid"},
             {"id": "node/b", "x": second_x, "y": 0, "width": 10, "height": 10, "status": "valid"}]
    for n in nodes:
        if lane:
            n["lane"] = {"relation": "node"}
        if group:
            n["group"] = {"relation": "node__group", "value": "g"}
    layout = encoded({"nodes": {n["id"]: [n[k] for k in ("x", "y", "width", "height")] for n in nodes}, "edges": {}})
    bands = [{"key": "kind:node", "axis": "x", "from": 0, "to": group_width}] if lane else []
    groups = [{"id": "group/g", "x": 0, "y": 0, "width": group_width, "height": 64}] if group else []
    root = "flow.synthetic/0/0_0.json"
    base = {"format": "rede.tile/1", "sheet": "flow.synthetic", "y": 0, "edges": [], "bands": bands, "groups": groups}
    if not tiled:
        tiles = {root: encoded(base | {"level": 0, "x": 0, "box": [0, 0, 64, 64], "nodes": nodes})}
    else:
        tiles, clusters = {}, []
        for x, n in enumerate(nodes):
            path = f"flow.synthetic/1/{x}_0.json"
            tiles[path] = encoded(base | {"level": 1, "x": x, "box": [x * 64, 0, 64, 64],
                                          "nodes": [n, nodes[0]] if repeated and x else [n]})
            clusters.append({"x": x, "y": 0, "box": [n[k] for k in ("x", "y", "width", "height")],
                             "count": 1, "statuses": [{"status": "valid", "count": 1}],
                             "first": {"id": n["id"]}, "last": {"id": n["id"]},
                             "sha256": hashlib.sha256(tiles[path]).hexdigest()})
        tiles[root] = encoded({"format": "rede.tile/1", "sheet": "flow.synthetic", "level": 0,
                               "x": 0, "y": 0, "box": [0, 0, 256, 256], "clusters": clusters})
    return dict(sheet="flow.synthetic", role=Role(snapshots, bundle), layout=layout,
                tiles=tiles, root=root, tile=64, fanout=4, levels=2 if tiled else 1)


def test_two_nodes_have_four_obligations_and_touching_the_edge_is_inside():
    result = containment(**fixture(second_x=54))
    assert (result.state, result.inside, result.total, result.outside, result.reason) == ("measured", 4, 4, (), None)


def test_outside_is_a_counted_layout_warning_not_an_invalid_view():
    result = containment(**fixture(second_x=28, group_width=32))
    assert (result.inside, result.total) == (2, 4)
    assert result.outside == (Outside("node/b", "group", "group/g"), Outside("node/b", "lane", "kind:node"))


def test_missing_group_geometry_cannot_earn_a_perfect_ratio():
    args = fixture()
    tile = json.loads(args["tiles"][args["root"]])
    tile["groups"] = []
    args["tiles"][args["root"]] = encoded(tile)
    result = containment(**args)
    assert (result.state, result.reason, result.inside, result.total) == ("unmeasurable", "group_geometry_unavailable", None, None)


def test_no_obligations_is_not_one_hundred_percent():
    result = containment(**fixture(lane=False, group=False))
    assert (result.state, result.reason, result.total) == ("unmeasurable", "no_containment_obligations", None)


def test_a_vertical_lane_uses_the_y_extent_and_missing_lane_geometry_is_unmeasurable():
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    piece["bands"][0].update(axis="y", to=5)
    args["tiles"][args["root"]] = encoded(piece)
    result = containment(**args)
    assert (result.inside, result.total) == (2, 4)
    assert result.outside == (Outside("node/a", "lane", "kind:node"), Outside("node/b", "lane", "kind:node"))
    piece["bands"] = []
    args["tiles"][args["root"]] = encoded(piece)
    result = containment(**args)
    assert (result.reason, result.inside, result.total) == ("lane_geometry_unavailable", None, None)


@pytest.mark.parametrize("selected", [frozenset(), frozenset({"not-a-leaf"})])
def test_unavailable_selection_is_explicit_and_does_not_echo_a_requested_id(selected):
    result = containment(**fixture(), selected=selected)
    assert (result.state, result.reason, result.scope, result.total) == ("unmeasurable", "leaf_scope_unavailable", (), None)


def test_repeated_tile_occurrence_is_counted_only_at_its_centre_and_inputs_stay_unchanged():
    args = fixture(second_x=70, group_width=128, tiled=True, repeated=True)
    before = copy.deepcopy((args["tiles"], args["layout"], args["role"].snapshots, args["role"].bundle))
    result = containment(**args)
    assert (result.inside, result.total, result.outside) == (4, 4, ())
    assert before == (args["tiles"], args["layout"], args["role"].snapshots, args["role"].bundle)


def test_selected_leaf_scope_cannot_be_mistaken_for_the_whole_sheet():
    args = fixture(second_x=70, group_width=128, tiled=True, repeated=True)
    path = "flow.synthetic/1/1_0.json"
    result = containment(**args, selected=frozenset({path}))
    assert (result.scope, result.inside, result.total) == ((path,), 2, 2)


def test_a_broken_parent_hash_is_not_a_measurement_warning():
    args = fixture(second_x=70, group_width=128, tiled=True)
    path = "flow.synthetic/1/1_0.json"
    args["tiles"][path] += b" "
    with pytest.raises(ValueError, match="^containment requires a valid role view$"):
        containment(**args)


def test_correctness_checks_still_cover_unselected_tiles_and_hide_unreadable_ids():
    args = fixture(second_x=70, group_width=128, tiled=True)
    args["role"] = Role({"node": encoded([{"key": ["b"]}]), "group": args["role"].snapshots["group"]}, args["role"].bundle)
    with pytest.raises(ValueError, match="^containment requires a valid role view$"):
        containment(**args, selected=frozenset({"flow.synthetic/1/1_0.json"}))


def test_a_wrong_quantity_is_not_downgraded_to_a_layout_warning():
    args = fixture()
    bundle = args["role"].bundle | {"arrows": [*args["role"].bundle["arrows"],
              {"id": "node.to", "table": "node__to", "kind": "node", "target": "node"}]}
    args["role"] = Role(args["role"].snapshots | {"node__to": encoded([{"key": ["a", "b"]}])}, bundle)
    edge = {"id": "node/a->node__to", "source": "node/a", "target": "node/b", "arrow": "node__to", "points": [],
            "quantity": {"slot": "not-a-quantity", "value": "7"}, "width": 28}
    layout = json.loads(args["layout"])
    layout["edges"] = {edge["id"]: {k: edge[k] for k in ("source", "target", "points")}}
    args["layout"] = encoded(layout)
    piece = json.loads(args["tiles"][args["root"]])
    piece["edges"] = [edge]
    args["tiles"][args["root"]] = encoded(piece)
    with pytest.raises(ValueError, match="^containment requires a valid role view$"):
        containment(**args)


def test_different_kinds_with_the_same_text_id_are_distinct_obligations():
    args = fixture()
    role = args["role"]
    bundle = role.bundle | {"kinds": [*role.bundle["kinds"], {"id": "other"}]}
    args["role"] = Role(role.snapshots | {"other": encoded([{"key": ["a"]}])}, bundle)
    piece = json.loads(args["tiles"][args["root"]])
    piece["nodes"].append({"id": "other/a", "x": 40, "y": 0, "width": 10, "height": 10,
                           "status": "valid", "lane": {"relation": "other"}})
    piece["bands"].append({"key": "kind:other", "axis": "y", "from": 0, "to": 64})
    args["tiles"][args["root"]] = encoded(piece)
    layout = json.loads(args["layout"])
    layout["nodes"]["other/a"] = [40, 0, 10, 10]
    args["layout"] = encoded(layout)
    result = containment(**args)
    assert (result.inside, result.total) == (5, 5)


def test_result_order_is_independent_of_dictionary_and_node_order():
    args = fixture(second_x=28, group_width=32)
    first = containment(**args)
    piece = json.loads(args["tiles"][args["root"]])
    piece["nodes"].reverse()
    args["tiles"][args["root"]] = encoded(piece)
    assert asdict(containment(**args)) == asdict(first)


@pytest.mark.parametrize("field,change,reason", [
    ("bands", {"from": 100, "to": 164}, "lane_geometry_conflict"),
    ("groups", {"x": 100}, "group_geometry_conflict"),
])
def test_conflicting_duplicate_containers_are_unmeasurable_in_both_array_orders(field, change, reason):
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    piece[field].append(piece[field][0] | change)
    for order in (piece[field], list(reversed(piece[field]))):
        args["tiles"][args["root"]] = encoded(piece | {field: order})
        result = containment(**args)
        assert (result.state, result.reason, result.inside, result.total, result.outside) == ("unmeasurable", reason, None, None, ())


@pytest.mark.parametrize("field", ["bands", "groups"])
def test_identical_duplicate_containers_do_not_inflate_counts(field):
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    piece[field].append(copy.deepcopy(piece[field][0]))
    for order in (piece[field], list(reversed(piece[field]))):
        args["tiles"][args["root"]] = encoded(piece | {field: order})
        result = containment(**args)
        assert (result.state, result.inside, result.total, result.outside) == ("measured", 4, 4, ())


def test_conflicting_geometry_does_not_mask_a_hard_role_error():
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    piece["groups"].append(piece["groups"][0] | {"x": 100})
    args["tiles"][args["root"]] = encoded(piece)
    args["role"] = Role({"group": args["role"].snapshots["group"]}, args["role"].bundle)
    with pytest.raises(ValueError, match="^containment requires a valid role view$"):
        containment(**args)
