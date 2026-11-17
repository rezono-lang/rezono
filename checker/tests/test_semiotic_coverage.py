"""Hand-counted element populations; no renderer or layout-derived denominator."""

import copy
from dataclasses import asdict
import hashlib
import json

import pytest

from rezono_checker.semiotic_coverage import flow_element_coverage
from rezono_checker.views import Role, check_view


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def fixture(*, drawn=("node/a", "node/b"), kinds=None, snapshots=None, bound=("node",), tiled=False):
    bundle = {"format": "rezono.schema-bundle/1", "kinds": kinds or [{"id": "node"}, {"id": "other"}],
              "attributes": [], "arrows": [], "channels": {"flows": [{"id": "synthetic",
              "title_message": "flow.synthetic", "nodes": [{"kind": k} for k in bound], "edges": []}]}}
    snapshots = snapshots if snapshots is not None else {"node": encoded([{"key": ["a"]}, {"key": ["b"]}])}
    nodes = [{"id": i, "x": j * (70 if tiled else 20), "y": 0, "width": 10, "height": 10,
              "status": "valid"} for j, i in enumerate(drawn)]
    root = "flow.synthetic/0/0_0.json"
    base = {"format": "rezono.tile/1", "sheet": "flow.synthetic", "y": 0, "edges": []}
    if tiled:
        tiles, clusters = {}, []
        for j, node in enumerate(nodes):
            path = f"flow.synthetic/1/{j}_0.json"
            tiles[path] = encoded(base | {"level": 1, "x": j, "box": [j * 64, 0, 64, 64], "nodes": [node]})
            clusters.append({"x": j, "y": 0, "box": [j * 64, 0, 64, 64], "count": 1,
                             "statuses": [{"status": "valid", "count": 1}], "first": {"id": node["id"]},
                             "last": {"id": node["id"]}, "sha256": hashlib.sha256(tiles[path]).hexdigest()})
        tiles[root] = encoded(base | {"level": 0, "x": 0, "box": [0, 0, 256, 256], "clusters": clusters})
    else:
        tiles = {root: encoded(base | {"level": 0, "x": 0, "box": [0, 0, 64, 64], "nodes": nodes})}
    layout = encoded({"nodes": {n["id"]: [n[k] for k in ("x", "y", "width", "height")] for n in nodes}, "edges": {}})
    return dict(sheet="flow.synthetic", role=Role(snapshots, bundle), layout=layout, tiles=tiles,
                root=root, tile=64, fanout=4, levels=2 if tiled else 1)


def change_bundle(args, change):
    bundle = copy.deepcopy(args["role"].bundle)
    change(bundle)
    args["role"] = Role(args["role"].snapshots, bundle)


def test_two_registered_elements_are_represented_without_containment_obligations():
    result = flow_element_coverage(**fixture())
    assert (result.state, result.represented, result.total, result.omitted, result.unexpected) == ("measured", 2, 2, (), ())


def test_self_consistent_layout_omission_is_measured_against_snapshots():
    args = fixture(drawn=("node/a",))
    assert check_view(args["sheet"], args["role"].snapshots, args["layout"], args["tiles"], args["root"],
                      args["tile"], args["fanout"], args["levels"], args["role"].bundle) == []
    result = flow_element_coverage(**args)
    assert (result.state, result.represented, result.total, result.omitted) == ("measured", 1, 2, ("node/b",))


def test_unrelated_role_rows_slots_and_derived_rows_are_not_extra_elements():
    args = fixture()
    bundle = args["role"].bundle | {"attributes": [{"id": "node.label", "table": "node__label", "kind": "node"}]}
    snapshots = args["role"].snapshots | {"other": encoded([{"key": ["noise"]}]),
        "node__label": encoded([{"key": ["a", "A"]}, {"key": ["b", "B"]}]),
        "derived": encoded([{"key": ["unregistered", "a"]}])}
    args["role"] = Role(snapshots, bundle)
    assert flow_element_coverage(**args).total == 2


def test_slot_subject_registers_one_element_without_an_own_kind_row():
    args = fixture(drawn=("node/a",), snapshots={"node__label": encoded([{"key": ["a", "A"]}])})
    change_bundle(args, lambda b: b.update(attributes=[{"id": "node.label", "table": "node__label", "kind": "node"}]))
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.omitted) == (1, 1, ())


def test_inherited_rows_collapse_at_the_readable_most_specific_kind():
    args = fixture(drawn=("child/a", "node/b"), kinds=[{"id": "node"}, {"id": "child", "parent": "node"}],
        snapshots={"node": encoded([{"key": ["a"]}, {"key": ["b"]}]), "child": encoded([{"key": ["a"]}])})
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.omitted) == (2, 2, ())


def test_unrelated_kinds_with_equal_text_ids_remain_distinct():
    args = fixture(drawn=("node/same",), bound=("node", "other"),
        snapshots={"node": encoded([{"key": ["same"]}]), "other": encoded([{"key": ["same"]}])})
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.omitted) == (1, 2, ("other/same",))


def test_readable_parent_is_not_downcast_to_a_hidden_child():
    args = fixture(drawn=(), bound=("child",), kinds=[{"id": "node"}, {"id": "child", "parent": "node"}],
        snapshots={"node": encoded([{"key": ["a"]}])})
    result = flow_element_coverage(**args)
    assert (result.state, result.total, result.represented, result.omitted, result.reason) == (
        "unmeasurable", 0, 0, (), "no_registered_in_scope_elements")


def test_unknown_lane_still_represents_its_registered_element():
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    for node in piece["nodes"]:
        node["lane"] = {"unknown": True}
    piece["bands"] = [{"key": "?", "axis": "x", "from": 0, "to": 64, "hatched": True}]
    args["tiles"][args["root"]] = encoded(piece)
    assert (flow_element_coverage(**args).represented, flow_element_coverage(**args).total) == (2, 2)


def test_placeholders_and_stubs_do_not_add_registered_elements():
    args = fixture(drawn=("node/a",))
    piece = json.loads(args["tiles"][args["root"]])
    layout = json.loads(args["layout"])
    stub = {"island": "other", "path": ["other"], "arrow": "node__to", "count": 9}
    for j, (node_id, status) in enumerate((("unknown/node/a/to", "unknown"), ("screened/node/a/to", "valid"),
                                         ("stub/other/to", "valid")), 1):
        node = {"id": node_id, "x": j * 10, "y": 20, "width": 5, "height": 5, "status": status}
        if node_id.startswith("stub/"):
            node["stub"] = stub
        piece["nodes"].append(node)
        layout["nodes"][node_id] = [j * 10, 20, 5, 5]
    args.update(layout=encoded(layout), stubs={"stub/other/to": stub})
    args["tiles"][args["root"]] = encoded(piece)
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.omitted, result.unexpected) == (1, 2, ("node/b",), ())


def test_readable_out_of_binding_nodes_do_not_inflate_numerator():
    args = fixture(drawn=("node/a", "other/noise"), snapshots={"node": encoded([{"key": ["a"]}]),
        "other": encoded([{"key": ["noise"]}])})
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.unexpected) == (1, 1, ("other/noise",))


def test_group_boxes_are_not_extra_node_elements():
    args = fixture()
    bundle = args["role"].bundle | {"kinds": [*args["role"].bundle["kinds"], {"id": "container"}],
        "arrows": [{"id": "node.group", "table": "node__group", "kind": "node", "target": "container"}]}
    args["role"] = Role(args["role"].snapshots | {"container": encoded([{"key": ["g"]}]),
        "node__group": encoded([{"key": ["a", "g"]}, {"key": ["b", "g"]}])}, bundle)
    piece = json.loads(args["tiles"][args["root"]])
    for node in piece["nodes"]:
        node["group"] = {"relation": "node__group", "value": "g"}
    piece["groups"] = [{"id": "container/g", "x": 0, "y": 0, "width": 64, "height": 64}]
    args["tiles"][args["root"]] = encoded(piece)
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.omitted) == (2, 2, ())


def test_route_only_rows_do_not_become_elements_or_a_table_only_coverage_claim():
    args = fixture(drawn=("node/a",))
    change_bundle(args, lambda b: b["channels"]["flows"][0].update(routes={
        "relation": "route", "from": "start", "to": "end", "from_kinds": ["node"], "to_kinds": ["node"]}))
    args["role"] = Role(args["role"].snapshots | {"route": encoded([{"key": ["a", "b"]}])}, args["role"].bundle)
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, result.omitted) == (1, 2, ("node/b",))
    assert "table_only" not in asdict(result)


def test_complete_tiled_scope_deduplicates_repeated_copies_and_preserves_inputs():
    args = fixture(tiled=True)
    path = "flow.synthetic/1/1_0.json"
    root = json.loads(args["tiles"][args["root"]])
    piece = json.loads(args["tiles"][path])
    piece["nodes"].append(json.loads(args["tiles"]["flow.synthetic/1/0_0.json"])["nodes"][0])
    args["tiles"][path] = encoded(piece)
    root["clusters"][1]["sha256"] = hashlib.sha256(args["tiles"][path]).hexdigest()
    args["tiles"][args["root"]] = encoded(root)
    before = copy.deepcopy((args["tiles"], args["layout"], vars(args["role"])))
    result = flow_element_coverage(**args)
    assert (result.represented, result.total, len(result.scope)) == (2, 2, 2)
    assert before == (args["tiles"], args["layout"], vars(args["role"]))
    args["tiles"] = dict(reversed(list(args["tiles"].items())))
    assert asdict(flow_element_coverage(**args)) == asdict(result)


@pytest.mark.parametrize("selected", [frozenset(), frozenset({"flow.synthetic/1/0_0.json"}), frozenset({"private/request"})])
def test_selected_observation_is_unmeasurable_not_a_filtered_denominator(selected):
    result = flow_element_coverage(**fixture(tiled=True), selected=selected)
    assert (result.reason, result.scope, result.represented, result.total) == ("whole_sheet_required", (), None, None)


@pytest.mark.parametrize("change", [
    lambda b: b.pop("format"),
    lambda b: b["channels"].update(flows=[]),
    lambda b: b["channels"]["flows"].append(copy.deepcopy(b["channels"]["flows"][0])),
    lambda b: b["channels"]["flows"][0].update(filter="active"),
    lambda b: b["channels"]["flows"][0]["nodes"][0].update(table_only=True),
    lambda b: b["channels"]["flows"][0].update(nodes=[{"kind": "missing"}]),
    lambda b: b["channels"]["flows"][0].update(nodes=[{"kind": "node"}, {"kind": "node"}]),
])
def test_missing_ambiguous_or_unsupported_population_never_fakes_zero_counts(change):
    args = fixture()
    change_bundle(args, change)
    result = flow_element_coverage(**args)
    assert (result.state, result.reason, result.total, result.represented) == (
        "unmeasurable", "flow_element_binding_unavailable", None, None)


def test_empty_registered_population_is_not_a_perfect_ratio():
    result = flow_element_coverage(**fixture(drawn=(), snapshots={}))
    assert (result.state, result.represented, result.total, result.reason) == (
        "unmeasurable", 0, 0, "no_registered_in_scope_elements")


@pytest.mark.parametrize("invalid", ["hidden", "broken_hash", "missing_tile"])
def test_full_validation_precedes_unsupported_binding_and_selected_scope(invalid):
    args = fixture(tiled=True)
    change_bundle(args, lambda b: b["channels"]["flows"][0].update(filter="unsupported"))
    if invalid == "hidden":
        args["role"] = Role({"node": encoded([{"key": ["a"]}])}, args["role"].bundle)
    elif invalid == "broken_hash":
        args["tiles"]["flow.synthetic/1/1_0.json"] += b" "
    else:
        del args["tiles"]["flow.synthetic/1/1_0.json"]
    with pytest.raises(ValueError, match="^coverage requires a valid role view$"):
        flow_element_coverage(**args, selected=frozenset({"flow.synthetic/1/0_0.json"}))


def test_invalid_quantity_is_not_downgraded_to_a_coverage_warning():
    args = fixture()
    bundle = args["role"].bundle | {"arrows": [{"id": "node.to", "table": "node__to", "kind": "node", "target": "node"}]}
    args["role"] = Role(args["role"].snapshots | {"node__to": encoded([{"key": ["a", "b"]}])}, bundle)
    edge = {"id": "node/a->node__to", "source": "node/a", "target": "node/b", "arrow": "node__to", "points": [],
            "quantity": {"slot": "not_a_quantity", "value": "7"}, "width": 28}
    layout = json.loads(args["layout"])
    layout["edges"] = {edge["id"]: {k: edge[k] for k in ("source", "target", "points")}}
    args["layout"] = encoded(layout)
    piece = json.loads(args["tiles"][args["root"]])
    piece["edges"] = [edge]
    args["tiles"][args["root"]] = encoded(piece)
    with pytest.raises(ValueError, match="^coverage requires a valid role view$"):
        flow_element_coverage(**args)
