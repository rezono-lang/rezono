"""Warning-only containment counts over one role's checked published view (M12).

No fetching, authentication, publication verdict or other semiotic metric lives here.
The caller supplies the existing authorised role snapshots and publication hash binding.
"""

from dataclasses import dataclass
import math

from .canon import strict_json_loads
from .views import Role, _placeholder, chain, check_view, group_of, lane_key


@dataclass(frozen=True, order=True)
class Outside:
    node: str
    container_type: str
    container: str


@dataclass(frozen=True)
class Containment:
    """Counts are obligations, not elements; None counts never mean perfect preservation."""

    scope: tuple[str, ...]
    inside: int | None = None
    total: int | None = None
    outside: tuple[Outside, ...] = ()
    reason: str | None = None

    @property
    def state(self) -> str:
        return "unmeasurable" if self.reason else "measured"


def containment(sheet: str, role: Role, layout: bytes, tiles: dict[str, bytes], root: str,
                tile: int, fanout: int, levels: int, *, selected: frozenset[str] | None = None,
                stubs: dict[str, dict] | None = None) -> Containment:
    """Check the entire supplied view first, then measure all or selected leaf tiles.

    `role` is the existing checker's rows, not a claim of authenticated identity. The
    caller still verifies the manifest/hash/role binding. Invalid views raise ValueError
    without echoing their potentially unreadable IDs. Layout warnings never raise it.
    Selection limits the metric's scope, never the correctness/access check.
    """
    try:
        problems = check_view(sheet, role.snapshots, layout, tiles, root, tile, fanout, levels,
                              role.bundle, stubs=stubs, role=role)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        raise ValueError("containment requires a valid role view") from None
    if problems:
        raise ValueError("containment requires a valid role view")
    pieces = {path: strict_json_loads(data) for path, data in tiles.items()}
    leaves = {path: piece for path, piece in pieces.items() if piece.get("level") == levels - 1}
    scope = tuple(sorted(leaves if selected is None else selected))
    if not scope or not set(scope) <= leaves.keys():
        return Containment((), reason="leaf_scope_unavailable")
    inside, total = 0, 0
    outside: set[Outside] = set()
    seen: dict[str, dict] = {}
    for path in scope:
        piece = leaves[path]
        bands = _containers(piece.get("bands", []), "key", ("axis", "from", "to"))
        groups_by_id = _containers(piece.get("groups", []), "id", ("x", "y", "width", "height"))
        if bands is None:
            return Containment(scope, reason="lane_geometry_conflict")
        if groups_by_id is None:
            return Containment(scope, reason="group_geometry_conflict")
        groups = sorted(groups_by_id.values(), key=lambda g: g["id"])
        for node in sorted(piece.get("nodes", []), key=lambda n: n["id"]):
            if _placeholder(node["id"]):
                continue
            x, y, w, h = (node[k] for k in ("x", "y", "width", "height"))
            if not _finite(x, y, w, h) or w < 0 or h < 0:
                return Containment(scope, reason="node_geometry_unavailable")
            # One placement may touch several tiles: its centre owns the obligation.
            if (int((x + w / 2) // tile), int((y + h / 2) // tile)) != (piece["x"], piece["y"]):
                continue
            if node["id"] in seen:
                if seen[node["id"]] != node:
                    return Containment(scope, reason="placement_conflict")
                continue
            seen[node["id"]] = node
            checks = []
            if "lane" in node:
                key = lane_key(node["id"], node["lane"], role.read, role.bundle)
                band = bands.get(key)
                if band is None or not _finite(band["from"], band["to"]) or band["to"] < band["from"]:
                    return Containment(scope, reason="lane_geometry_unavailable")
                start, size = (x, w) if band["axis"] == "x" else (y, h)
                checks.append(("lane", key, start >= band["from"] and start + size <= band["to"]))
            if "group" in node:
                member = group_of(node["id"], node["group"], role.read, role.bundle)
                group = next((g for g in groups if member in _group_kinds(g["id"], role.bundle)), None)
                if group is None or not _finite(*(group[k] for k in ("x", "y", "width", "height"))) \
                        or group["width"] < 0 or group["height"] < 0:
                    return Containment(scope, reason="group_geometry_unavailable")
                checks.append(("group", group["id"], x >= group["x"] and y >= group["y"]
                               and x + w <= group["x"] + group["width"]
                               and y + h <= group["y"] + group["height"]))
            for kind, key, holds in checks:
                total += 1
                inside += int(holds)
                if not holds:
                    outside.add(Outside(node["id"], kind, key))
    if not total:
        return Containment(scope, reason="no_containment_obligations")
    return Containment(scope, inside, total, tuple(sorted(outside)))


def _finite(*values) -> bool:
    return all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _containers(items: list[dict], key: str, geometry: tuple[str, ...]) -> dict[str, dict] | None:
    out = {}
    for item in items:
        previous = out.get(item[key])
        if previous is not None and any(previous[k] != item[k] for k in geometry):
            return None
        out[item[key]] = item
    return out


def _group_kinds(node_id: str, bundle: dict) -> set[tuple[str, str]]:
    kind, _, row = node_id.partition("/")
    return {(k, row) for k in chain(bundle, kind)}
