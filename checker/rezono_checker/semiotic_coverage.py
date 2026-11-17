"""Warning-only registered-element coverage of a whole, unfiltered published Flow."""

from dataclasses import dataclass
import json

from .semiotic import _finite
from .views import Role, _placeholder, chain, check_view


@dataclass(frozen=True)
class FlowElementCoverage:
    scope: tuple[str, ...]
    represented: int | None = None
    total: int | None = None
    omitted: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def state(self) -> str:
        return "unmeasurable" if self.reason else "measured"


def flow_element_coverage(sheet: str, role: Role, layout: bytes, tiles: dict[str, bytes], root: str,
                          tile: int, fanout: int, levels: int, *, selected: frozenset[str] | None = None,
                          stubs: dict[str, dict] | None = None) -> FlowElementCoverage:
    """Check the full view first; count registered elements independently of its layout.

    The caller supplies the existing authorised snapshots and manifest/hash binding;
    Role is not authentication. A selected viewport is not this whole-sheet metric.
    Field, edge-source row and table-only coverage are deliberately not reported.
    """
    try:
        problems = check_view(sheet, role.snapshots, layout, tiles, root, tile, fanout, levels,
                              role.bundle, stubs=stubs, role=role)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise ValueError("coverage requires a valid role view") from None
    if problems:
        raise ValueError("coverage requires a valid role view")
    if selected is not None:
        return FlowElementCoverage((), reason="whole_sheet_required")
    kinds = _node_kinds(role.bundle, sheet)
    if kinds is None:
        return FlowElementCoverage((), reason="flow_element_binding_unavailable")
    pieces = {path: json.loads(data) for path, data in tiles.items()}
    leaves = {path: piece for path, piece in pieces.items() if piece.get("level") == levels - 1}
    scope = tuple(sorted(leaves))
    if not scope:
        return FlowElementCoverage((), reason="leaf_scope_unavailable")
    expected = {(kind, row) for kind, row in role.once if kinds.intersection(chain(role.bundle, kind))}
    drawn = set()
    for piece in leaves.values():
        for node in piece.get("nodes", []):
            if _placeholder(node["id"]):
                continue
            x, y, w, h = (node[k] for k in ("x", "y", "width", "height"))
            if not _finite(x, y, w, h) or w < 0 or h < 0:
                return FlowElementCoverage(scope, reason="node_geometry_unavailable")
            if (int((x + w / 2) // tile), int((y + h / 2) // tile)) == (piece["x"], piece["y"]):
                kind, _, row = node["id"].partition("/")
                drawn.add((kind, row))
    return FlowElementCoverage(scope, len(expected & drawn), len(expected),
                               tuple(sorted(f"{k}/{i}" for k, i in expected - drawn)),
                               tuple(sorted(f"{k}/{i}" for k, i in drawn - expected)),
                               None if expected else "no_registered_in_scope_elements")


def _node_kinds(bundle: dict, sheet: str) -> set[str] | None:
    """Only today's compiled, unfiltered Flow-node population has defined semantics."""
    if bundle.get("format") != "rede.schema-bundle/1":
        return None
    flows = [f for f in bundle.get("channels", {}).get("flows", []) if sheet == f"flow.{f.get('id')}"]
    if len(flows) != 1:
        return None
    flow = flows[0]
    if set(flow) - {"id", "title_message", "nodes", "edges", "direction", "routes"}:
        return None
    if not isinstance(flow.get("title_message"), str) or not isinstance(flow.get("edges"), list) \
            or flow.get("direction", "right") not in ("down", "right"):
        return None
    nodes = flow.get("nodes")
    if not isinstance(nodes, list) or not nodes or any(not isinstance(n, dict) or
            set(n) - {"kind", "label", "lane", "group"} or not isinstance(n.get("kind"), str) for n in nodes):
        return None
    kinds = {n["kind"] for n in nodes}
    known = [k["id"] for k in bundle.get("kinds", [])]
    if len(kinds) != len(nodes) or any(known.count(k) != 1 for k in kinds):
        return None
    return kinds
