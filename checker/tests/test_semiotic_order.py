"""Manual contract fixtures for enum-lane geometry/counts; not actual compiler publications."""
import copy
from dataclasses import asdict
import hashlib
import json

import pytest

from rezono_checker.semiotic_order import lane_order
from rezono_checker.views import Role


SHEET = "flow.synthetic"
VALUES = ["low", "middle", "high"]


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def fixture(*, centres=(10, 30, 20), direction="right", tiled=False, repeated=False, values=VALUES):
    # emit.bundle writes slot IDs in channels and fully qualified enum value IDs.
    attr = {"id": "node.rank", "kind": "node", "name": "rank", "table": "node__rank", "type": "enum",
            "schema_type": "Rank", "enum": "Rank", "multivalued": False, "required": False, "derivation": "fact"}
    flow = {"id": "synthetic", "direction": direction, "title_message": "flow.title",
            "nodes": [{"kind": "node", "lane": {"channel": "lane", "slot": "node.rank", "level": "ordered", "meaning_message": "rank"}}],
            "edges": [{"arrow": "node.next"}]}
    bundle = {"format": "rezono.schema-bundle/1", "kinds": [{"id": "node"}], "attributes": [attr],
              "arrows": [{"id": "node.next", "kind": "node", "table": "node__next", "target": "node"}],
              "enums": [{"id": "Rank", "values": [f"Rank.{v}" for v in values]}], "channels": {"flows": [flow]}}
    rows = [("z", values[0]), ("a", values[1]), ("m", values[2]), ("n", values[2]), ("u", None)]
    snapshots = {"node": encoded([{"key": [i]} for i, _ in rows]),
                 "node__rank": encoded([{"key": [i, v]} for i, v in rows if v is not None])}
    axis = "x" if direction == "right" else "y"
    positions = dict(zip(values, centres))
    bands = [{"key": f"enum:Rank:{v}", "axis": axis, "from": c - 5, "to": c + 5} for v, c in positions.items()]
    bands.append({"key": "?", "axis": axis, "from": 40, "to": 50, "hatched": True})
    nodes = []
    for index, (row, value) in enumerate(rows):
        position = positions[value] - 5 if value is not None else 40
        cross = index * (64 if tiled else 12)
        x, y = (position, cross) if axis == "x" else (cross, position)
        nodes.append({"id": f"node/{row}", "x": x, "y": y, "width": 10, "height": 10, "status": "valid",
                      "lane": {"relation": "node__rank", "value": value} if value is not None else {"unknown": True}})
    layout = encoded({"nodes": {n["id"]: [n[k] for k in ("x", "y", "width", "height")] for n in nodes}, "edges": {}})
    root = f"{SHEET}/0/0_0.json"
    base = {"format": "rezono.tile/1", "sheet": SHEET, "edges": [], "bands": bands}
    if not tiled:
        tiles = {root: encoded(base | {"level": 0, "x": 0, "y": 0, "box": [0, 0, 64, 64], "nodes": nodes})}
    else:
        tiles, clusters = {}, []
        for index, node in enumerate(nodes):
            x, y = (0, index) if axis == "x" else (index, 0)
            path = f"{SHEET}/1/{x}_{y}.json"
            tiles[path] = encoded(base | {"level": 1, "x": x, "y": y, "box": [x * 64, y * 64, 64, 64],
                                          "nodes": [node, nodes[0]] if repeated and index else [node]})
            clusters.append({"x": x, "y": y, "box": [node[k] for k in ("x", "y", "width", "height")],
                             "count": 1, "statuses": [{"status": "valid", "count": 1}],
                             "first": {"id": node["id"]}, "last": {"id": node["id"]}, "sha256": hashlib.sha256(tiles[path]).hexdigest()})
        tiles[root] = encoded({"format": "rezono.tile/1", "sheet": SHEET, "level": 0, "x": 0, "y": 0,
                               "box": [0, 0, 512, 512], "clusters": clusters})
    return dict(sheet=SHEET, kind="node", role=Role(snapshots, bundle), layout=layout, tiles=tiles,
                root=root, tile=64, fanout=8, levels=2 if tiled else 1)


def counts(result):
    return result.eligible, result.preserved, result.ties, result.unknown_pairs, result.drawn_ties


@pytest.mark.parametrize("direction", ["right", "down"])
def test_manual_pair_partition_is_exact_and_uses_the_declared_axis(direction):
    result = lane_order(**fixture(direction=direction))
    assert (result.state, counts(result)) == ("measured", (5, 3, 1, 4, 0))
    assert result.eligible + result.ties + result.unknown_pairs == 10


def test_ids_and_shared_lane_rows_do_not_replace_declared_enum_order():
    args = fixture(centres=(10, 20, 30))
    assert counts(lane_order(**args)) == (5, 5, 1, 4, 0)
    args["role"].bundle["enums"][0]["values"].reverse()
    assert counts(lane_order(**args)) == (5, 0, 1, 4, 0)


@pytest.mark.parametrize("values", [("", ".leading", "with.dot"), ("Rank.low", "same", "zeta")])
def test_exact_enum_prefix_preserves_legal_raw_suffixes_and_input(values):
    args = fixture(centres=(10, 20, 30), values=values)
    before = copy.deepcopy(args["role"].bundle)
    assert counts(lane_order(**args)) == (5, 5, 1, 4, 0)
    assert args["role"].bundle == before


@pytest.mark.parametrize("value", ["low", "Rank", "Rankful.low", "Other.low", ".Rank.low"])
def test_wrong_or_missing_own_prefix_is_not_guessed(value):
    args = fixture()
    args["role"].bundle["enums"][0]["values"][0] = value
    result = lane_order(**args)
    assert (result.state, result.reason, result.eligible) == ("unmeasurable", "ordered_enum_binding_unavailable", None)


def test_globally_ambiguous_enum_element_is_not_used_as_a_rank():
    args = fixture()
    args["role"].bundle["enums"].append({"id": "Rank.low", "values": ["Rank.low"]})
    assert lane_order(**args).reason == "ordered_enum_binding_unavailable"


def test_equal_raw_suffix_in_a_different_enum_is_not_ambiguous():
    args = fixture(centres=(10, 20, 30))
    args["role"].bundle["enums"].append({"id": "Other", "values": ["Other.low"]})
    assert counts(lane_order(**args)) == (5, 5, 1, 4, 0)


@pytest.mark.parametrize("values", [[], ["Rank.low", "Rank.low"], [None], "Rank.low"])
def test_invalid_enum_sequences_are_unmeasurable(values):
    args = fixture()
    args["role"].bundle["enums"][0]["values"] = values
    assert lane_order(**args).reason == "ordered_enum_binding_unavailable"


@pytest.mark.parametrize("level", [None, "nominal", "ordinal"])
def test_enum_declaration_order_without_the_actual_ordered_binding_proves_nothing(level):
    args = fixture()
    lane = args["role"].bundle["channels"]["flows"][0]["nodes"][0]["lane"]
    if level is None:
        del lane["level"]
    else:
        lane["level"] = level
    result = lane_order(**args)
    assert (result.state, result.reason, result.eligible) == ("unmeasurable", "ordered_enum_binding_unavailable", None)


@pytest.mark.parametrize("change", ["flow", "kind", "slot", "enum", "multi", "normalised-only"])
def test_binding_identity_must_resolve_against_real_raw_bundle_fields(change):
    args = fixture()
    bundle = args["role"].bundle
    flow = bundle["channels"]["flows"][0]
    if change == "flow":
        flow["id"] = "different"
    elif change == "kind":
        flow["nodes"][0]["kind"] = "different"
    elif change == "slot":
        flow["nodes"][0]["lane"]["slot"] = "other.rank"
    elif change == "enum":
        bundle["enums"][0]["id"] = "Different"
    elif change == "multi":
        bundle["attributes"][0]["multivalued"] = True
    else:
        bundle["bindings"] = bundle.pop("channels")
    assert lane_order(**args).reason == "ordered_enum_binding_unavailable"


def test_zero_denominator_is_unmeasurable_and_published_unknown_is_not_rank_zero():
    args = fixture(tiled=True)
    # Two high rows share a lane: a real tie, not an eligible comparison.
    result = lane_order(**args, selected=frozenset({f"{SHEET}/1/0_2.json", f"{SHEET}/1/0_3.json"}))
    assert (result.state, counts(result), result.reason) == ("unmeasurable", (0, 0, 1, 0, 0), "no_strict_comparable_pairs")
    result = lane_order(**args, selected=frozenset({f"{SHEET}/1/0_4.json"}))
    assert (result.state, counts(result)) == ("unmeasurable", (0, 0, 0, 0, 0))


def test_drawn_equal_centres_do_not_preserve_strict_data_order():
    result = lane_order(**fixture(centres=(20, 20, 30)))
    assert counts(result) == (5, 4, 1, 4, 1)


def test_selected_scope_duplicate_tiles_permutation_and_inputs_are_stable():
    args = fixture(tiled=True, repeated=True)
    before = copy.deepcopy((args["role"].snapshots, args["role"].bundle, args["layout"], args["tiles"]))
    result = lane_order(**args)
    assert counts(result) == (5, 3, 1, 4, 0)
    selected = frozenset({f"{SHEET}/1/0_0.json", f"{SHEET}/1/0_2.json"})
    part = lane_order(**args, selected=selected)
    assert (part.scope, counts(part)) == (tuple(sorted(selected)), (1, 1, 0, 0, 0))
    assert before == (args["role"].snapshots, args["role"].bundle, args["layout"], args["tiles"])
    args["tiles"] = dict(reversed(list(args["tiles"].items())))
    assert asdict(lane_order(**args)) == asdict(result)


def test_known_role_cell_cannot_be_downgraded_to_unknown_for_the_metric():
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    piece["nodes"][0]["lane"] = {"unknown": True}
    piece["bands"] = [b for b in piece["bands"] if b["key"] != "enum:Rank:low"]
    args["tiles"][args["root"]] = encoded(piece)
    assert lane_order(**args).reason == "binding_lane_mismatch"


def test_unselected_hard_role_error_is_not_hidden_by_nominal_or_metric_scope():
    args = fixture(tiled=True)
    snapshots = args["role"].snapshots | {"node": encoded([{"key": ["a"]}]), "node__rank": encoded([])}
    args["role"] = Role(snapshots, args["role"].bundle)
    args["role"].bundle["channels"]["flows"][0]["nodes"][0]["lane"]["level"] = "nominal"
    with pytest.raises(ValueError, match="^containment requires a valid role view$"):
        lane_order(**args, selected=frozenset({f"{SHEET}/1/0_1.json"}))


@pytest.mark.parametrize("coordinate", [float("inf"), float("nan")])
def test_nonfinite_band_geometry_is_unmeasurable_without_a_fraction(coordinate):
    args = fixture()
    piece = json.loads(args["tiles"][args["root"]])
    piece["bands"][0]["to"] = coordinate
    args["tiles"][args["root"]] = encoded(piece)
    with pytest.raises(ValueError, match="^containment requires a valid role view$"):
        lane_order(**args)


def test_conflicting_cross_tile_band_geometry_is_not_a_stable_lane_order():
    args = fixture(tiled=True)
    path = f"{SHEET}/1/0_1.json"
    piece = json.loads(args["tiles"][path])
    piece["bands"][0].update({"from": 50, "to": 60})
    args["tiles"][path] = encoded(piece)
    root = json.loads(args["tiles"][args["root"]])
    root["clusters"][1]["sha256"] = hashlib.sha256(args["tiles"][path]).hexdigest()
    args["tiles"][args["root"]] = encoded(root)
    result = lane_order(**args)
    assert (result.reason, result.eligible, result.preserved) == ("lane_geometry_conflict", None, None)
