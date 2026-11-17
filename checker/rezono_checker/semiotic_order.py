"""Warning-only row-pair order of one explicitly ordered enum lane binding."""

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
import json

from .semiotic import _containers, _finite, containment
from .views import Role, _placeholder, chain


@dataclass(frozen=True)
class LaneOrder:
    scope: tuple[str, ...]
    eligible: int | None = None
    preserved: int | None = None
    ties: int | None = None
    unknown_pairs: int | None = None
    drawn_ties: int | None = None
    reason: str | None = None

    @property
    def state(self) -> str:
        return "unmeasurable" if self.reason else "measured"


def lane_order(sheet: str, kind: str, role: Role, layout: bytes, tiles: dict[str, bytes], root: str,
               tile: int, fanout: int, levels: int, *, selected: frozenset[str] | None = None,
               stubs: dict[str, dict] | None = None) -> LaneOrder:
    """One binding from the raw compiled bundle, never an asserted ordinal flag.

    The existing containment boundary checks the entire role view exactly once before
    selection. Its caller still supplies verified role and manifest/hash binding. This
    measures lane-band centres, not node placement or quantity correctness.
    """
    checked = containment(sheet, role, layout, tiles, root, tile, fanout, levels, selected=selected, stubs=stubs)
    scope = checked.scope
    if checked.reason:
        return LaneOrder(scope, reason=checked.reason)
    binding = _binding(role.bundle, sheet, kind)
    if binding is None:
        return LaneOrder(scope, reason="ordered_enum_binding_unavailable")
    flow, attribute, values = binding
    ranks = {v: i for i, v in enumerate(values)}
    pieces = [json.loads(tiles[path]) for path in scope]
    bands = _containers([b for piece in pieces for b in piece.get("bands", [])], "key", ("axis", "from", "to"))
    if bands is None:
        return LaneOrder(scope, reason="lane_geometry_conflict")
    axis = "x" if flow.get("direction", "right") == "right" else "y"
    drawn_kinds = {n["kind"] for n in flow["nodes"]}
    candidates = {}
    for piece in pieces:
        for node in piece.get("nodes", []):
            node_id = node["id"]
            if _placeholder(node_id):
                continue
            actual, _, row = node_id.partition("/")
            if next((k for k in chain(role.bundle, actual) if k in drawn_kinds), None) != kind:
                continue
            if (int((node["x"] + node["width"] / 2) // tile), int((node["y"] + node["height"] / 2) // tile)) != (piece["x"], piece["y"]):
                continue
            cells = [key[1] for key in role.read.get(attribute["table"], set()) if len(key) == 2 and key[0] == row]
            lane = node.get("lane")
            if not cells and lane == {"unknown": True}:
                candidates[node_id] = (None, None)
                continue
            if len(cells) != 1 or cells[0] not in ranks or lane != {"relation": attribute["table"], "value": cells[0]}:
                return LaneOrder(scope, reason="binding_lane_mismatch")
            key = f"enum:{attribute['enum']}:{cells[0]}"
            band = bands.get(key)
            if band is None or band["axis"] != axis or not _finite(band["from"], band["to"]):
                return LaneOrder(scope, reason="lane_geometry_unavailable")
            # Twice the centre, compared exactly for the supplied finite coordinates.
            centre = Fraction(band["from"]) + Fraction(band["to"])
            candidates[node_id] = (ranks[cells[0]], centre)
    eligible = preserved = ties = unknown = drawn_ties = 0
    for (a, x), (b, y) in combinations((candidates[k] for k in sorted(candidates)), 2):
        if a is None or b is None:
            unknown += 1
        elif a == b:
            ties += 1
        else:
            eligible += 1
            preserved += int(x < y if a < b else y < x)
            drawn_ties += int(x == y)
    return LaneOrder(scope, eligible, preserved, ties, unknown, drawn_ties,
                     None if eligible else "no_strict_comparable_pairs")


def _binding(bundle: dict, sheet: str, kind: str):
    """Resolve compiled slot IDs exactly as bundleFromCompiler normalises them."""
    if bundle.get("format") != "rezono.schema-bundle/1":
        return None
    flows = [f for f in bundle.get("channels", {}).get("flows", []) if sheet == f"flow.{f.get('id')}"]
    if len(flows) != 1 or flows[0].get("direction", "right") not in ("down", "right"):
        return None
    flow = flows[0]
    nodes = [n for n in flow.get("nodes", []) if n.get("kind") == kind]
    if len(nodes) != 1 or not any(k.get("id") == kind for k in bundle.get("kinds", [])):
        return None
    lane = nodes[0].get("lane", {})
    if lane.get("channel") != "lane" or lane.get("level") != "ordered" or not lane.get("meaning_message"):
        return None
    attrs = [a for a in bundle.get("attributes", []) if a.get("id") == lane.get("slot")]
    if len(attrs) != 1:
        return None
    attr = attrs[0]
    if attr.get("kind") not in chain(bundle, kind) or attr.get("type") != "enum" \
            or attr.get("multivalued") is not False or not attr.get("table") or not attr.get("enum"):
        return None
    enums = [e for e in bundle.get("enums", []) if e.get("id") == attr["enum"]]
    if len(enums) != 1:
        return None
    values = enums[0].get("values")
    if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values) or len(set(values)) != len(values):
        return None
    # The wire contract names enum elements; role snapshots hold their raw suffixes.
    # Keep empty/dotted suffixes and the supplied sequence, removing only the own prefix.
    prefix = f"{attr['enum']}."
    if any(not value.startswith(prefix) for value in values):
        return None
    if any(value in other.get("values", []) for other in bundle.get("enums", [])
           if other is not enums[0] for value in values):
        return None
    return flow, attr, [value[len(prefix):] for value in values]
