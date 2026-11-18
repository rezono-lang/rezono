"""A published view never shows more than its role may read (docs/gui.md, Work per request: O(page)).

A view of a sheet is a whole layout (`<sheet>/layout.json`) and a pyramid of tiles cut from it. A tile holds
no text: per node its place, its status and the cell its label shows; per line its ends, its arrow and its
route. The checker recomputes each of these from the role's snapshots and trusts nothing it is given:

- every node of the layout is an element the role reads: a row of one of its snapshots of that kind, by the
  kind relation `k` or a slot relation `k__a` the bundle names (as the viewer turns snapshots into rows;
  a check or derived relation is no element), drawn once, at the most specific kind the role reads it as
  (an element of a subkind is in its supertypes' tables too). A placeholder hangs from such a row;
- a node's status is the one the viewer's rows give it (every cell of a snapshot row is known, so a row is
  valid; an unknown end is unknown; a screened end is valid), and the cell it shows is a row of the role's
  snapshot of that slot: `[id, value]`, with the node's own id (an inherited slot's table names the kind
  that declares it, so it need not be the node's kind);
- every part of a node's name is rows the role reads: `[id, value]` in the name's relation, the id being
  the node's own or, for a name made from its ends, one its arrow row `[node id, end id]` reaches. The
  same holds for every name the page index lists;
- a line is an arrow row the role reads: `[source id, target id]` in the arrow's snapshot, of an arrow of the
  source's kind or one of its supertypes. A screened line
  hangs from an arrow row of its source; an unknown end from its source. Ends and routes are the layout's;
- a stub on an island's Map shows exactly what the island levels give it (`island_plan`): the island it
  opens, by key and path, its arrow and the number of lines it stands for; a line to it hangs from an arrow
  row of its source and is named `source->arrow`, or `source->arrow->stub` for a multivalued arrow
  (`stub_line`), and a line from a stub of lines coming in (`direction: in`) ends at an arrow row into its
  element;
- every tile is reached from the root by the sha256 its parent names, and every cluster's count and
  statuses are recomputed from the layout: the nodes, not placeholders, whose centre lies in its tile. So are
  its guide words: the first and the last of those nodes in guide order (by the Z place of the last-level
  tile that holds a node's centre, then top to bottom, left to right and by id), each with a name that is
  rows the role reads. Every node of the layout is drawn in the last-level tile that holds its centre, so a
  view cannot count elements it does not draw.

Ids are those of the viewer's map: `kind/id`, `unknown/kind/id/arrow`, `screened/kind/id/arrow`, and
`stub/<island>/<arrow>` or, on an island laid out as an index, `stub/kind/id/<island>/<arrow>`, and for lines
coming in `stub/in/<island>/<arrow>` or `stub/in/kind/id/<island>/<arrow>`. A kind holds
no `/`; an id may.

A sheet is `map`, `map.<island>`, `flow.<id>`, `matrix.<id>`, `timeline.<id>` or `nest.<id>`; any
other kind is refused.
A Timeline (`timeline.<id>`, TimelineSheet in contracts/view.yaml) is rows and nothing else: its nodes are
exactly the elements of the binding's row kind that the role reads, it holds no line, and in a tile each row
holds `dates`, a list in the binding's order (the start, the end, the extension where bound, then the marks):
`{relation, state: known, value}` where that is the role's one row of the attribute. Where the role reads no
such row, the start and the end are there as `{relation, state: unknown}`; the extension and a mark are there
as unknown where that is the answer, and not there where the row has none (`lacking`: optional, a closed
relation, read in full). Its only cell is the binding's judgement.
A Nest (`nest.<id>`, NestSheet, one sheet per binding; an element's id is never part of a sheet name) is parts
and nothing else: every element of the first level the role reads; every element of a later level whose
container, the role's one row of the level's `part_of`
arrow, is a part; and every element of a later level the role reads no container of while that container is
unknown (`lacking`), which stands apart with its own parts. An element known to have no container is a part
of nothing and stands on no sheet. In a tile a part holds its container as its `group` (`{relation, value}`,
or `{unknown: true}` apart) and, per perspective over a relation, `states`: exactly the role's rows of that
relation for the part; without a row `[]` where the part has none, `{unknown: true}` where that is unknown.

A sheet may also have lanes and lines of other relations (a Flow, docs/gui.md): the same checks hold, read
generally, with no binding:

- a line is rows the role reads of its sign: an arrow row `[source, target]` (of an arrow of the source's
  kind), a link row that reaches both ends (`[link, target]` in the sign, `[link, source]` in another arrow of
  the key of a link kind: a kind whose first unique key holds only single-valued arrows), or a row of a
  relation that holds both ids. `rows`, where a line has it, is exactly how many
  such rows give its pair. A line of a sheet with more lines per source is named `source->sign->target`;
- a node's `lane` is the cell of its own row that puts it there (for a Matrix's head, the row of the element it
  shows: a Board's column): its kind's table (`relation` only, a kind of
  its chain), a row `[id, value]` the role reads, or `unknown`. Its key is `kind:<kind>`, `kind:<target>:<id>`
  for an arrow, `enum:<enum>:<value>` for an enum attribute, `?` for unknown. A tile holds the lanes (bands)
  it crosses: each band is the lane of a node of the sheet, and a band that is an arrow's target is named by
  rows the role reads. That a band keeps one extent across tiles, does not overlap the next and holds the
  nodes of its lane is layout: a warning, never a block (AGENTS.md, rule 5);
- a line's `quantity` (a band) is the sum of its slot over those rows: an integer column of the relation, or
  the integer attribute of the link kind over its links, each known; its `width` is layout;
- a node's `group` is the cell of its own row that puts it in a group: a row `[id, value]` the role reads of an
  arrow of its kind. A tile holds the groups (boxes) it crosses: each is an element the role reads, at its
  most specific kind, the group of a node of the sheet, and named by rows the role reads. That a box keeps one
  place across tiles and holds its members is layout: a warning.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import NamedTuple

from .canon import INTEGER
from .snapshots import read_rows


def rows(snapshots: dict[str, bytes]) -> dict[str, set[tuple[str, ...]]]:
    """The keys of every row the role reads, by relation."""
    return {relation: {parts for parts, _ in read_rows(data, "json").values()} for relation, data in snapshots.items()}


def element_relations(bundle: dict) -> dict[str, str]:
    """{relation: kind} for the relations that hold elements, from the compiled bundle: each kind's own
    relation, and each slot table (attribute or arrow), whose kind is the part before `__`."""
    out = {k["id"]: k["id"] for k in bundle.get("kinds", [])}
    for slot in [*bundle.get("attributes", []), *bundle.get("arrows", [])]:
        out[slot["table"]] = slot["table"].split("__", 1)[0]
    return out


def elements(read: dict, bundle: dict) -> set[tuple[str, str]]:
    """(kind, id) of every element in the role's rows ({relation: keys}), by the bundle's kind and slot
    relations only."""
    of = element_relations(bundle)
    return {(of[relation], parts[0]) for relation, keys in read.items() if relation in of for parts in keys if parts}


def chain(bundle: dict, kind: str) -> list[str]:
    """The kind and its supertypes, nearest first."""
    parent = {k["id"]: k.get("parent") for k in bundle.get("kinds", [])}
    out: list[str] = []
    while kind and kind not in out:
        out.append(kind)
        kind = parent.get(kind)
    return out


def most_specific(found: set[tuple[str, str]], bundle: dict) -> set[tuple[str, str]]:
    """Each element once, at its most specific kind, as the viewer draws and counts it
    (layout/elements.ts): an element of a subkind is in its supertypes' tables too, so drop a (kind, id) when
    the same id is found at a kind below it."""
    kinds: dict[str, list[str]] = {}
    for kind, i in found:
        kinds.setdefault(i, []).append(kind)
    above = {k: set(chain(bundle, k)[1:]) for k in {kind for kind, _ in found}}
    return {(kind, i) for kind, i in found if not any(kind in above[k] for k in kinds[i])}


class Role:
    """What one role reads, derived once from its snapshots and the bundle: its rows by relation, its elements,
    each at its most specific kind, and its island plan. Every check of the role's views uses the same one,
    made by the checker from the snapshots alone, never from what the publisher made. `full` is the relations
    the role reads in full: the `full` flag of its snapshots in the manifest, which the access
    check has verified before any view is made (rezono_checker.access). Without it no relation counts as read in
    full, so a missing row is never read as "none" (`lacking`)."""

    def __init__(self, snapshots: dict[str, bytes], bundle: dict, full=frozenset()):
        self.snapshots, self.bundle, self.full = snapshots, bundle, frozenset(full)
        self.read = rows(snapshots)
        self.readable = elements(self.read, bundle)
        self.once = most_specific(self.readable, bundle)
        self._plan: IslandPlan | None = None

    @property
    def plan(self) -> "IslandPlan":
        if self._plan is None:
            self._plan = island_plan(self.snapshots, self.bundle, self)
        return self._plan


def _readable(node_id: str, readable: set[tuple[str, str]]) -> bool:
    kind, _, rest = node_id.partition("/")
    if (kind, rest) in readable:
        return True
    if kind in ("unknown", "screened") and "/" in rest:
        anchor, _, _arrow = rest.rpartition("/")
        k, _, i = anchor.partition("/")
        return (k, i) in readable
    return False


def _placeholder(node_id: str) -> bool:
    return node_id.startswith(("unknown/", "screened/", "stub/"))


PART = {"relation", "id", "value", "via"}


def _name(row: str, name, read: dict) -> bool:
    """Whether every part of a name is rows the role reads (layout/names.ts in the viewer): `[id, value]` in
    its relation, where the id is the row's own, or an end the arrow row `[row, id]` in `via` reaches. A part
    without a relation names its end by its id, so it needs that arrow row."""
    if not isinstance(name, list) or not name:
        return False
    for part in name:
        if not isinstance(part, dict) or set(part) - PART or not isinstance(part.get("id"), str):
            return False
        via, end = part.get("via"), part["id"]
        if via is None and (end != row or "relation" not in part):
            return False
        if via is not None and (row, end) not in read.get(via, set()):
            return False
        if ("relation" in part or "value" in part) and (end, part.get("value")) not in read.get(part.get("relation"), set()):
            return False
    return True


def check_page(snapshots: dict[str, bytes], bundle: dict, page: bytes, role: Role | None = None) -> list[str]:
    """Problems with a role's page index: every listed id is a row the role reads of that kind, every name is
    rows the role reads, and each count is exactly the rows of that kind the role reads (a larger one would tell
    about hidden rows, a smaller one is a wrong page), each element counted once, at its most specific kind."""
    role = role or Role(snapshots, bundle)
    read = role.read
    by_kind: dict[str, set[str]] = {}
    for kind, i in role.once:
        by_kind.setdefault(kind, set()).add(i)
    problems = []
    for entry in json.loads(page).get("kinds", []):
        kind, ids = entry["kind"], by_kind.get(entry["kind"], set())
        if entry["count"] != len(ids):
            problems.append(f"page: kind {kind} counts {entry['count']}, the role reads {len(ids)}")
        for row in entry["first"]:
            i = row.get("id") if isinstance(row, dict) else None
            if i not in ids or set(row) - {"id", "name"}:
                problems.append(f"page: {kind}/{i} is no row the role reads")
            elif "name" in row and not _name(i, row["name"], read):
                problems.append(f"page: {kind}/{i} has a name that is no rows the role reads: {row['name']}")
    return problems


NODE = {"id", "x", "y", "width", "height", "status", "name", "cell", "image", "stub", "lane", "group", "of"}
EDGE = {"id", "source", "target", "arrow", "points"}
BAND = {"key", "axis", "from", "to", "hatched", "name"}
GROUP = {"id", "x", "y", "width", "height", "name"}
UNKNOWN_LANE = "?"
SHEETS = {"map", "flow", "matrix", "timeline", "nest"}  # a sheet is `<kind>` or `<kind>.<id>`; any other kind is refused


def lane_key(node_id: str, lane, read: dict, bundle: dict) -> str | None:
    """The key of the lane a node's `lane` cell puts it in, or None where that cell is no row the role reads."""
    if lane == {"unknown": True}:
        return UNKNOWN_LANE
    if not isinstance(lane, dict) or set(lane) - {"relation", "value"} or not isinstance(lane.get("relation"), str):
        return None
    kind, _, row = node_id.partition("/")
    relation = lane["relation"]
    if "value" not in lane:
        return f"kind:{relation}" if relation in chain(bundle, kind) else None
    if (row, lane["value"]) not in read.get(relation, set()):
        return None
    arrow = next((a for a in bundle.get("arrows", []) if a["table"] == relation), None)
    if arrow:
        return f"kind:{arrow['target']}:{lane['value']}"
    attribute = next((a for a in bundle.get("attributes", []) if a["table"] == relation and a.get("enum")), None)
    return f"enum:{attribute['enum']}:{lane['value']}" if attribute else None


def group_of(node_id: str, group, read: dict, bundle: dict) -> tuple[str, str] | None:
    """(the arrow's target kind, the group's id) a node's `group` cell puts it in, or None where that cell is no
    row the role reads of an arrow of its kind."""
    if not isinstance(group, dict) or set(group) != {"relation", "value"}:
        return None
    kind, _, row = node_id.partition("/")
    arrow = next((a for a in bundle.get("arrows", []) if a["table"] == group["relation"]), None)
    if arrow is None or arrow.get("kind") not in chain(bundle, kind) or (row, group["value"]) not in read.get(arrow["table"], set()):
        return None
    return arrow["target"], group["value"]


def ends(bundle: dict, kind: str) -> set[str]:
    """The arrow tables of a link kind's ends: its first unique key (or a supertype's) that holds only
    single-valued arrows (the compiler's `Pack.ends`). Empty: the kind is no link kind."""
    arrows = {a["id"]: a for a in bundle.get("arrows", []) if "id" in a}
    for k in chain(bundle, kind):
        for key in bundle.get("unique_keys", []):
            if key.get("kind") == k and key.get("slots") and all(s in arrows and not arrows[s].get("multivalued") for s in key["slots"]):
                return {arrows[s]["table"] for s in key["slots"]}
    return set()


def stub_line(source: str, table: str, stub: str, bundle: dict) -> str:
    """The id of a line from `source` by the arrow `table` to `stub` (docs/gui.md, Zoom: islands by meaning):
    `source->arrow` for a single-valued arrow, `source->arrow->stub` for a multivalued one, whose lines from
    one source can end at stubs of several islands."""
    many = any(a.get("table") == table and a.get("multivalued") for a in bundle.get("arrows", []))
    return f"{source}->{table}->{stub}" if many else f"{source}->{table}"


def _image(node_id: str, image, read: dict, bundle: dict) -> bool:
    """An image is the bound cell of this element, from this role's rows; no asset URL or hidden cell."""
    if (not isinstance(image, dict) or set(image) != {"relation", "value"}
            or not isinstance(image.get("relation"), str)):
        return False
    kind, _, row = node_id.partition("/")
    bindings = (bundle.get("channels") or {}).get("images") or []
    binding = next((b for k in chain(bundle, kind) for b in bindings if b.get("kind") == k), None)
    attr = next((a for a in bundle.get("attributes", []) if binding and a.get("id") == binding.get("slot")), None)
    value = image.get("value")
    # A relative pack file, never an address. The asset checker independently verifies its bytes/index.
    if (not isinstance(value, str) or not value or value.startswith(("/", "\\")) or ":" in value
            or "\\" in value or any(p in ("", ".", "..") for p in value.split("/"))):
        return False
    return bool(attr and attr.get("table") == image.get("relation")
                and (row, value) in read.get(attr["table"], set()))


def _node(n: dict, read: dict, stubs: dict[str, dict], bundle: dict) -> list[str]:
    """What a tile shows of a node, recomputed from the role's rows (a stub's, from the island levels)."""
    node_id = n["id"]
    if set(n) - NODE:
        return [f"node {node_id} holds more than its place, status, name and cell: {sorted(set(n) - NODE)}"]
    if node_id.startswith("stub/"):
        ok = n["status"] == "valid" and not {"cell", "name", "image"} & set(n) and n.get("stub") == stubs.get(node_id)
        return [] if ok else [f"stub {node_id} shows {n.get('stub')}, the island levels give {stubs.get(node_id)}"]
    if "stub" in n:
        return [f"node {node_id} is no stub, yet shows one"]
    if node_id.startswith("unknown/"):
        return [] if n["status"] == "unknown" and not {"cell", "name", "image", "lane", "group"} & set(n) else [f"unknown end {node_id} is not shown as unknown"]
    if node_id.startswith("screened/"):
        return [] if n["status"] == "valid" and not {"cell", "name", "image", "lane", "group"} & set(n) else [f"screened end {node_id} shows more than a screened end"]
    _, _, row = n.get("of", node_id).partition("/")
    problems = [] if n["status"] == "valid" else [f"node {node_id} has status {n['status']!r}, its rows give valid"]
    cell = n.get("cell")
    if cell is not None:
        relation = cell.get("relation", "")
        attribute = next((a for a in bundle.get("attributes", []) if a.get("table") == relation), None)
        amount = attribute is not None and attribute.get("type") == "integer" and "currency" in attribute
        value = cell.get("minor_units" if amount else "value")
        fields = {"relation", "state", "minor_units", "currency"} if amount else {"relation", "state", "value"}
        typed = (not amount or (isinstance(value, str) and INTEGER.fullmatch(value)
                 and str(int(value)) == value and isinstance(attribute.get("currency"), str)
                 and cell.get("currency") == attribute["currency"]))
        if (cell.get("state") != "known" or set(cell) != fields or not typed
                or (row, value) not in read.get(relation, set())):
            problems.append(f"node {node_id} shows a cell that is no row the role reads: {cell}")
    if "name" in n and not _name(row, n["name"], read):
        problems.append(f"node {node_id} shows a name that is no rows the role reads: {n['name']}")
    if "image" in n and not _image(n.get("of", node_id), n["image"], read, bundle):
        problems.append(f"node {node_id} shows an image that is no bound cell the role reads")
    return problems


def _counts(source: str, target: str | None, sign: str, read: dict, bundle: dict, columns: list | None = None) -> dict:
    """How many rows the role reads give a line of `sign` from node `source` to node `target`, per way they can
    (empty: none): a relation's pair of columns, or one way for an arrow or a link kind; with `target` None,
    whether any hangs from `source`. A node is its kind and id, so an
    arrow row counts only between the arrow's own kinds: an arrow of the source's kind (or a supertype) to the
    target's kind (or a supertype). An arrow row of a link kind reaches its end, and another arrow of the link
    kind's key, to the source's kind, its start (only of a link kind: `ends`); a relation's row holds both ids,
    the pair counted per two of its columns, or with `columns` (its from and to) in those two only."""
    skind, _, sid = source.partition("/")
    tkind, _, tid = target.partition("/") if target is not None else (None, "", None)
    arrows = {a["table"]: a for a in bundle.get("arrows", [])}
    arrow = arrows.get(sign)
    got = read.get(sign, set())
    if arrow is None:
        if tid is None:
            return {"any": 1} if any(sid in k for k in got) else {}
        by: dict = {}
        names = [c.get("name") for r in bundle.get("relations", []) if r.get("id") == sign for c in r.get("columns", [])]
        if columns is not None and not (isinstance(columns, list) and len(columns) == 2 and all(c in names for c in columns)):
            return {}
        only = (names.index(columns[0]), names.index(columns[1])) if columns is not None else None
        for k in got:
            for i, j in {(i, j) for i in range(len(k)) for j in range(len(k)) if i != j and k[i] == sid and k[j] == tid}:
                if only is not None and (i, j) != only:
                    continue
                by[(i, j)] = by.get((i, j), 0) + 1
        return by
    if tkind is not None and arrow.get("target", tkind) not in chain(bundle, tkind):
        return {}
    if arrow.get("kind", sign.split("__", 1)[0]) in chain(bundle, skind) and any(len(k) == 2 and k[0] == sid and (tid is None or k[1] == tid) for k in got):
        return {"arrow": 1}
    key = ends(bundle, arrow.get("kind", ""))
    if sign not in key:
        return {}
    others = sorted(o for o in key - {sign} if arrows[o].get("target", skind) in chain(bundle, skind))
    links = {k[0] for o in others for k in read.get(o, set()) if len(k) == 2 and k[1] == sid}
    n = sum(1 for k in got if len(k) == 2 and k[0] in links and (tid is None or k[1] == tid))
    return {"link": n} if n else {}


def _edge(e: dict, read: dict, bundle: dict, of: dict[str, str] | None = None) -> list[str]:
    """A line, recomputed from the role's rows of its sign. `of`: per node whose id is not its element, the
    element it shows; a line between such nodes is the rows between those elements."""
    if set(e) - {"rows", "quantity", "width", "columns"} != EDGE:
        return [f"line {e.get('id')} is not ends, arrow and route: {sorted(e)}"]
    if of and (e["source"] in of or e["target"] in of):
        if e["id"] != f"{e['source']}->{e['arrow']}->{e['target']}" or e["arrow"] in ("unknown_end", "screened") \
                or "quantity" in e or "width" in e:
            return [f"line {e['id']} is not named by its ends and sign, or is more than rows between them"]
        if "columns" not in e and not any(a.get("table") == e["arrow"] for a in bundle.get("arrows", [])):
            return [f"line {e['id']} is a relation's rows between elements, but does not say its columns"]
        e = dict(e, id=f"{of.get(e['source'], e['source'])}->{e['arrow']}->{of.get(e['target'], e['target'])}",
                 source=of.get(e["source"], e["source"]), target=of.get(e["target"], e["target"]))
    source, target, arrow = e["source"], e["target"], e["arrow"]
    _, _, sid = source.partition("/")
    # A line to a stub, an unknown or a screened end has no rows behind both ends to sum: it is never a band.
    if (target.startswith("stub/") or arrow in ("unknown_end", "screened")) and {"quantity", "width"} & set(e):
        return [f"line {e['id']} ends at a stub, an unknown or a screened end, yet shows a quantity or a width"]
    if source.startswith("stub/"):
        # A line from another island into an element: named by its stub, arrow and element, from an arrow row the
        # role reads into that element. Which island it comes from is checked against the island levels.
        tkind, _, tid = target.partition("/")
        ends = [a for a in bundle.get("arrows", []) if a.get("table") == arrow]
        if {"quantity", "width"} & set(e) or e["id"] != f"{source}->{arrow}->{target}" or not source.endswith(f"/{arrow}") \
                or _placeholder(target) or not any(a["target"] in chain(bundle, tkind) for a in ends):
            return [f"line {e['id']} is not named by its stub, arrow and element, or comes in by another arrow"]
        if not any(len(k) == 2 and k[1] == tid for k in read.get(arrow, set())):
            return [f"line {e['id']} from a stub ends at no arrow row the role reads"]
        return []
    if target.startswith("stub/"):
        # Which island it ends at is checked against the island levels (check_islands).
        if e["id"] != stub_line(source, arrow, target, bundle) or not target.endswith(f"/{arrow}") or arrow.split("__", 1)[0] not in chain(bundle, source.partition("/")[0]):
            return [f"line {e['id']} is not named by its source and arrow (and stub, for a multivalued arrow), or ends at a stub of another arrow"]
        if not any(k[0] == sid for k in read.get(arrow, set())):
            return [f"line {e['id']} to a stub hangs from no arrow row the role reads"]
        return []
    if arrow in ("unknown_end", "screened"):
        prefix = "unknown" if arrow == "unknown_end" else "screened"
        if not target.startswith(f"{prefix}/{source}/"):
            return [f"line {e['id']} does not end at its own {prefix} end"]
        slot = target[len(f"{prefix}/{source}/"):]
        if e["id"] not in (f"{source}->{slot}", f"{source}->{slot}->{target}") or "rows" in e:
            return [f"line {e['id']} is not named by its source and arrow"]
        if arrow == "screened" and not _counts(source, None, slot, read, bundle):
            return [f"screened line {e['id']} hangs from no row the role reads"]
        return []
    _, _, tid = target.partition("/")
    if e["id"] not in (f"{source}->{arrow}", f"{source}->{arrow}->{target}"):
        return [f"line {e['id']} is not named by its source and arrow"]
    # An arrow row between the ends' own kinds (declared there or on a supertype), a link row, or a relation row.
    counts = _counts(source, target, arrow, read, bundle, e.get("columns"))
    if not counts:
        return [f"line {e['id']} is no row the role reads"]
    # Its number of rows and its quantity hold in one and the same way (a relation's pair of columns), never
    # the number in one way and the sum in another.
    ways = {w for w, n in counts.items() if n == e.get("rows", 1)}
    if not ways:
        return [f"line {e['id']} says {e.get('rows', 1)} rows, the role reads {sorted(counts.values())}"]
    if "quantity" in e:
        sums = _sums(source, target, arrow, e["quantity"], read, bundle)
        if not any(sums.get(w) == e["quantity"].get("value") for w in ways):
            return [f"line {e['id']} says a quantity of {e['quantity']}, which is no sum of rows the role reads in the way it counts them"]
    width = e.get("width")
    if width is not None and ("quantity" not in e or isinstance(width, bool) or not isinstance(width, (int, float)) or width <= 0):
        return [f"line {e['id']} has a width but no quantity, or no positive width"]
    return []


def _cell(e: dict, matrix: dict, shows: dict[str, str], bundle: dict) -> list[str]:
    """A Matrix's cell as its binding has it: from a row's head to a column's head, of the binding's sign, and for a
    relation exactly its `from` and `to` columns, with ends of `from_kinds` and `to_kinds`. A cell whose ends and
    columns are both turned round would hold as rows, so the binding, not the cell, fixes the direction."""
    source, target = str(e.get("source")), str(e.get("target"))
    if not (source.startswith("rows/") and target.startswith("columns/")):
        return [f"cell {e.get('id')} is not from a row's head to a column's head"]
    if e.get("arrow") != matrix["sign"] or e.get("columns") != matrix["columns"]:
        return [f"cell {e.get('id')} is not of the Matrix's source: sign {e.get('arrow')}, columns {e.get('columns')}"]
    for end, kinds in ((source, matrix["from_kinds"]), (target, matrix["to_kinds"])):
        if kinds is not None and not set(kinds) & set(chain(bundle, shows.get(end, "").partition("/")[0])):
            return [f"cell {e.get('id')} ends at {end}, which is of none of {kinds}"]
    return []


def _sums(source: str, target: str, sign: str, quantity, read: dict, bundle: dict) -> dict:
    """The sums of a quantity's slot over the rows the role reads that give a line of `sign` from `sid` to `tid`,
    as decimal text, per way they can, keyed as `_counts`: a relation's integer column, per two of its columns
    holding the ids; or the integer attribute of a link kind over its links that reach both ends, each known.
    Empty: none."""
    if not isinstance(quantity, dict) or set(quantity) != {"slot", "value"}:
        return {}
    (skind, _, sid), (_, _, tid) = source.partition("/"), target.partition("/")
    slot = quantity["slot"]
    arrows = {a["table"]: a for a in bundle.get("arrows", [])}
    arrow = arrows.get(sign)
    try:
        if arrow is None:
            relation = next((r for r in bundle.get("relations", []) if r.get("id") == sign), {})
            columns = [c["name"] for c in relation.get("columns", [])]
            if not any(c["name"] == slot and c.get("type") == "integer" for c in relation.get("columns", [])):
                return {}
            c = columns.index(slot)
            by: dict = {}
            for k in read.get(sign, set()):
                for i, j in {(i, j) for i in range(len(k)) for j in range(len(k)) if i != j and k[i] == sid and k[j] == tid}:
                    by[(i, j)] = by.get((i, j), 0) + int(k[c])
            return {w: str(v) for w, v in by.items()}
        attribute = next((a for a in bundle.get("attributes", []) if a["table"] == slot), None)
        key = ends(bundle, arrow.get("kind", ""))
        if attribute is None or attribute.get("kind") not in chain(bundle, arrow.get("kind", "")) or sign not in key:
            return {}
        # Through the key's other arrows to the source's kind only, as `_counts` (a node is its kind and id).
        others = [o for o in key - {sign} if arrows[o].get("target", skind) in chain(bundle, skind)]
        links = {k[0] for o in others for k in read.get(o, set()) if len(k) == 2 and k[1] == sid}
        reach = {k[0] for k in read.get(sign, set()) if len(k) == 2 and k[0] in links and k[1] == tid}
        values = {k[0]: int(k[1]) for k in read.get(slot, set()) if len(k) == 2 and k[0] in reach}
        return {"link": str(sum(values.values()))} if reach and set(values) == reach else {}
    except ValueError:
        return {}


def z_index(x: int, y: int) -> int:
    """The place of tile (x, y) on the Z curve: its bits interleaved, x in the even ones (tiles.ts, zIndex)."""
    z, b = 0, 0
    while x >> b or y >> b:
        z |= ((x >> b) & 1) << (2 * b) | ((y >> b) & 1) << (2 * b + 1)
        b += 1
    return z


def matrix_cells(sheet: str, bundle: dict) -> dict | None:
    """For a Matrix sheet (`matrix.<id>`), what its binding in the compiled bundle (`channels.matrices`) allows:
    the kind of each axis, the sign of a cell as a tile names it (an arrow's table, a link kind's `to` arrow's
    table, or the relation), the columns a relation's cell names (its `from` and `to`, in that order; none for an
    arrow or a link kind), and the kinds a relation's ends may have. None: no such sheet or binding."""
    kind, _, name = sheet.partition(".")
    if kind != "matrix":
        return None
    binding = next((m for m in bundle.get("channels", {}).get("matrices", []) if m.get("id") == name), None)
    if binding is None:
        return None
    tables = {a["id"]: a["table"] for a in bundle.get("arrows", []) if "id" in a and "table" in a}
    cells = binding["cells"]
    out = {"axes": {"rows": binding["rows"]["kind"], "columns": binding["columns"]["kind"]}, "columns": None,
           "from_kinds": None, "to_kinds": None}
    if "relation" in cells:
        return out | {"sign": cells["relation"], "columns": [cells["from"], cells["to"]],
                      "from_kinds": cells["from_kinds"], "to_kinds": cells["to_kinds"]}
    return out | {"sign": tables.get(cells["arrow"] if "arrow" in cells else cells["to"])}


def lacking(relation: str, declared: dict, optional: bool, full: frozenset) -> str:
    """What a missing row of `relation` says to a role: `none` where a row may be missing (an
    optional slot, or a derived relation), the relation is closed and the role reads it in full: missing is
    not true. `unknown` in every other case: a required slot without its row, an open relation, or a relation
    the role does not read in full. `declared` is the slot or the relation as the bundle has it (`world`, left
    out: closed); read in full is the role's snapshot flag (`Role.full`), never a look at the rows."""
    return "none" if optional and declared.get("world", "closed") == "closed" and relation in full else "unknown"


def timeline_dates(sheet: str, bundle: dict) -> dict | None:
    """For a Timeline sheet (`timeline.<id>`), what its binding in the compiled bundle (`channels.timelines`,
    TimelineSheet in contracts/view.yaml) binds: the kind of its rows, the relation of every date a row shows
    (`start`, `end`, the `extension` and each mark) and the relation of its judgement. The binding names an
    attribute by its element id (`<kind>.<slot>`, the kind that declares it), as the compiler writes every
    binding; the relation is that attribute's table. `dates` is in the binding's order: the start, the end,
    then the extension where bound and the marks; `slots` is each date's attribute as the bundle has it, by
    relation. None: no such sheet or binding, or a binding that names something that is no attribute of the
    bundle, or one date twice."""
    kind, _, name = sheet.partition(".")
    if kind != "timeline":
        return None
    binding = next((t for t in bundle.get("channels", {}).get("timelines", []) if t.get("id") == name), None)
    if binding is None:
        return None
    tables = {a["id"]: a["table"] for a in bundle.get("attributes", []) if "id" in a and "table" in a}
    table = lambda slot: tables.get(slot) if isinstance(slot, str) else None  # noqa: E731
    marks = binding.get("marks") or []
    dates = [table(binding.get("start")), table(binding.get("end")), *([table(binding["extension"])] if "extension" in binding else []),
             *(table(m.get("slot")) if isinstance(m, dict) else None for m in marks)]
    judgement = table((binding["judgement"] or {}).get("slot")) if isinstance(binding.get("judgement"), dict) else None
    if not isinstance(binding.get("rows"), str) or None in dates or len(set(dates)) != len(dates) or ("judgement" in binding) != (judgement is not None):
        return None
    slots = {a["table"]: a for a in bundle.get("attributes", []) if a.get("table") in dates}
    return {"rows": binding["rows"], "dates": dates, "slots": slots, "judgement": judgement}


def _timeline_row(n: dict, timeline: dict, values: dict[str, dict[str, set[str]]], full: frozenset = frozenset()) -> list[str]:
    """What a tile shows of a Timeline's row beyond its node: its dates, a list in the binding's order with no
    relation twice and none the binding does not name. Where the role reads a row of the attribute, the date
    is there as `known` with that one row's value. Where it reads none, the start and the end are there as
    `unknown` (an end nobody stated is unknown, never "no end"), and the extension and a mark show one of two
    answers, each exact both ways (`lacking`): no entry where the row has none, `unknown` where it is unknown.
    And no cell but its judgement. `values` is the role's rows of those attributes, by relation and element
    id; `full` the relations the role reads in full."""
    node_id = n["id"]
    row = node_id.partition("/")[2]
    dates, order = n.get("dates"), timeline["dates"]
    named = [d.get("relation") for d in dates if isinstance(d, dict)] if isinstance(dates, list) else None
    if named is None or len(named) != len(dates) or named != [r for r in order if r in named]:
        return [f"row {node_id} does not show its dates as a list of its Timeline's dates, each once and in the binding's order: {', '.join(order)}"]
    shown = dict(zip(named, dates))
    problems = []
    for at, relation in enumerate(order):
        date, mine, slot = shown.get(relation), values[relation].get(row, set()), timeline["slots"][relation]
        # Without a row of the role's: unknown for the start and the end, none or unknown for the others.
        without = "unknown" if at < 2 else lacking(relation, slot, slot.get("required") is False, full)
        if date is None:
            if mine:
                problems.append(f"row {node_id} does not show {relation}, the role reads {sorted(mine)}")
            elif without == "unknown":
                problems.append(f"row {node_id} does not show {relation}: the role reads no row of it, so it is unknown and is shown as unknown")
        elif date == {"relation": relation, "state": "unknown"}:
            if mine:
                problems.append(f"row {node_id} shows {relation} as unknown, the role reads {sorted(mine)}")
            elif without == "none":
                problems.append(f"row {node_id} shows {relation} as unknown: it is optional and the role reads its closed relation in full, so the row has none")
        elif set(date) == {"relation", "state", "value"} and date["state"] == "known" and isinstance(date["value"], str):
            if mine != {date["value"]}:
                problems.append(f"row {node_id} shows {relation} as {date['value']!r}, the role reads {sorted(mine) or 'no such row'}")
        else:
            problems.append(f"row {node_id} shows a date of {relation} that is neither known nor unknown: {date}")
    cell = n.get("cell")
    if cell is not None and (not isinstance(cell, dict) or timeline["judgement"] is None or cell.get("relation") != timeline["judgement"]):
        problems.append(f"row {node_id} shows a cell that is not the judgement of its Timeline: {cell}")
    return problems


APART = {"unknown": True}  # a Nest's part whose container the role does not read: it stands in no container


def nest_levels(sheet: str, bundle: dict) -> dict | None:
    """For a Nest sheet (`nest.<id>`, one per binding), what its binding in the compiled bundle
    (`channels.nests`, NestSheet in contracts/view.yaml) binds: the kind of each level from the outside in,
    each level's `part_of` arrow and its table (none for the first), and per perspective over a relation that
    relation as the bundle has it, the place of its `part` column and of the columns a state shows (the
    `origin`, where it names one, then the state). The binding names an arrow by its element id and a column
    by its name, as the compiler writes them. None: no such sheet or binding, or a binding whose arrows or
    columns the bundle does not have. An element's id is no part of the sheet's name: the page of one element
    reads it from this sheet, and the element is a segment of the page's address."""
    kind, _, name = sheet.partition(".")
    binding = next((n for n in bundle.get("channels", {}).get("nests", []) if n.get("id") == name), None)
    if kind != "nest" or binding is None or not isinstance(binding.get("levels"), list) or len(binding["levels"]) < 2:
        return None
    arrows = {a["id"]: a for a in bundle.get("arrows", []) if "id" in a and "table" in a}
    declared = {r["id"]: r for r in bundle.get("relations", []) if "id" in r}
    columns = {i: [c.get("name") for c in r.get("columns", [])] for i, r in declared.items()}
    kinds: list[str] = []
    tables: list[str | None] = [None]
    part_of: list[dict | None] = [None]
    for level in binding["levels"]:
        if not isinstance(level, dict) or not isinstance(level.get("kind"), str) or level["kind"] in kinds:
            return None
        if kinds:
            arrow = arrows.get(level.get("part_of")) if isinstance(level.get("part_of"), str) else None
            if arrow is None or arrow.get("target") != kinds[-1] or arrow.get("kind") not in chain(bundle, level["kind"]):
                return None
            tables.append(arrow["table"])
            part_of.append(arrow)
        kinds.append(level["kind"])
    views: dict[str, tuple[str, int, list[int]]] = {}
    for p in binding.get("perspectives") or []:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or p["id"] in views:
            return None
        if "relation" not in p:
            continue
        state = p["state"].get("slot") if isinstance(p.get("state"), dict) else None
        named = [p.get("part"), *([p["origin"]] if "origin" in p else []), state]
        of = columns.get(p["relation"]) if isinstance(p["relation"], str) else None
        if of is None or any(not isinstance(c, str) or c not in of for c in named) or len(set(named)) != len(named):
            return None
        views[p["id"]] = (p["relation"], of.index(named[0]), [of.index(c) for c in named[1:]])
    return {"kinds": kinds, "tables": tables, "arrows": part_of, "views": views,
            "relations": {view: declared[relation] for view, (relation, _, _) in views.items()}}


def nest_parts(nest: dict, read: dict, once: set[tuple[str, str]], bundle: dict,
               full: frozenset = frozenset()) -> tuple[dict[str, object], list[str]]:
    """The parts of a Nest's sheet from the role's rows: ({node id: its container's id, APART where its
    container is unknown, None for an element of the first level}, the problems of a level that holds one id
    twice). Every element of the first level the role reads is a part. An element of a later level is a part
    when the role's one row of the level's arrow names a part of the level before it, or when the role reads no
    such row and the container is unknown (`lacking`: a required arrow, an open relation, or one the role does
    not read in full): it stands apart, once, with its own parts inside it. An element known to have no
    container (an optional arrow, a closed relation the role reads in full, no row) is a part of nothing: on
    no sheet. So is an element whose container the role reads no element of, or one with two containers.
    A container is named by its id alone, so two elements of one level with one id (two kinds below the
    level's) are refused: which one a part lies in would be a guess. `full` is the relations the role reads in
    full."""
    def level_of(kind: str) -> int | None:
        return next((nest["kinds"].index(k) for k in chain(bundle, kind) if k in nest["kinds"]), None)

    at: list[dict[str, str]] = [{} for _ in nest["kinds"]]
    twice = []
    for kind, i in sorted(once):
        level = level_of(kind)
        if level is not None:
            if i in at[level]:
                twice.append(f"{at[level][i]} and {kind}/{i} are two elements of level {nest['kinds'][level]} with one id")
            at[level][i] = f"{kind}/{i}"
    parts: dict[str, object] = {node: None for node in at[0].values()}
    inside = set(at[0])
    for level in range(1, len(at)):
        container: dict[str, set[str]] = {}
        for row in read.get(nest["tables"][level], set()):
            if len(row) == 2:
                container.setdefault(row[0], set()).add(row[1])
        here = set()
        arrow = nest["arrows"][level]
        apart = lacking(nest["tables"][level], arrow, arrow.get("required") is False, full) == "unknown"
        for i, node in at[level].items():
            holds = container.get(i, set())
            if (not holds and apart) or (len(holds) == 1 and holds <= inside):
                parts[node] = next(iter(holds)) if holds else APART
                here.add(i)
        inside = here
    return parts, twice


def _nest_part(n: dict, parts: dict, tables: dict[str, str], states: dict[str, dict[str, list]], without: dict[str, object]) -> list[str]:
    """What a tile shows of a Nest's part beyond its node: its container, as `group` (the row of its level's
    arrow, or APART), and per perspective over a relation its states, exactly the role's rows of that relation
    for this part (`states`: {perspective: [[origin, state] or [state], ...]}, sorted). Where the role reads no
    row for the part, `without` has the perspective's answer: `[]`, the part has none, or APART, it is unknown
    (`lacking`); the other of the two is refused."""
    node_id = n["id"]
    if node_id not in parts:
        return []  # no part of the sheet: found with the layout
    want, group = parts[node_id], n.get("group")
    problems = []
    if want is None:
        if group is not None:
            problems.append(f"part {node_id} is the element the sheet is of, yet stands in a container: {group}")
    elif want is APART:
        if group != APART:
            problems.append(f"part {node_id} stands in a container the role reads no row of: {group}")
    elif group == APART:
        problems.append(f"part {node_id} stands apart as unknown, the role reads its container {want}")
    elif group != {"relation": tables[node_id], "value": want}:
        problems.append(f"part {node_id} stands in {group}, the role's row of {tables[node_id]} says {want}")
    mine = {view: by.get(node_id.partition("/")[2]) or without[view] for view, by in states.items()}
    if n.get("states", {}) != mine or ("states" in n) != bool(mine):
        problems.append(f"part {node_id} shows states that are not the role's rows of its perspectives: {n.get('states')}")
    return problems


def check_view(sheet: str, snapshots: dict[str, bytes], layout: bytes, tiles: dict[str, bytes], root: str,
               tile: int, fanout: int, levels: int, bundle: dict, stubs: dict[str, dict] | None = None,
               warnings: list[str] | None = None, role: Role | None = None) -> list[str]:
    """Problems with one sheet's view for one role: `tiles` by path, `root` the path of the level-0 tile,
    `tile`, `fanout` and `levels` the pyramid's measures, `stubs` what each stub of the sheet shows (from
    `island_plan`). Empty: the view shows only what the role reads. Layout that is off (lanes) goes to
    `warnings`, where given."""
    warnings = [] if warnings is None else warnings
    stubs = stubs or {}
    problems: list[str] = []
    role = role or Role(snapshots, bundle)
    read, readable, once = role.read, role.readable, role.once
    whole = json.loads(layout)
    nodes = whole.get("nodes", {})
    lines = whole.get("edges", {})
    # A node that is not its element (an element that stands on the sheet more than once) says which it shows.
    shows = whole.get("of", {})
    if not isinstance(shows, dict) or set(shows) - set(nodes) or any(_placeholder(i) or _placeholder(str(x)) for i, x in shows.items()):
        problems.append(f"{sheet}: the layout says a node shows an element, but it is no node, or a placeholder")
        shows = {}
    # Only a Matrix has such nodes, each a head named by its axis and its element (`rows/<of>`, `columns/<of>`),
    # so the id a page shows is the element the checker checks. Its cells follow the binding in the bundle.
    matrix = matrix_cells(sheet, bundle)
    if sheet.startswith("matrix.") and matrix is None:
        problems.append(f"{sheet}: no Matrix of the bundle has this sheet")
    if matrix is None and shows:
        problems.append(f"{sheet}: the layout says nodes show other elements, but only a Matrix has such nodes")
        shows = {}
    if matrix is not None:
        for node_id in sorted(nodes):
            axis, _, of = node_id.partition("/")
            if axis not in matrix["axes"] or shows.get(node_id) != of or matrix["axes"][axis] not in chain(bundle, of.partition("/")[0]):
                problems.append(f"{sheet}: node {node_id} is no head {axis}/<element> of an element of its axis kind")
        for edge_id, e in sorted(lines.items()):
            if not (str(e.get("source")).startswith("rows/") and str(e.get("target")).startswith("columns/")):
                problems.append(f"{sheet}: line {edge_id} is no cell from a row's head to a column's head")
    # A Timeline is its rows and nothing else: one node per element of its row kind that the role reads, each
    # with its dates (in the tile, `_timeline_row`), no line, no stub and no placeholder. Its binding is the
    # bundle's; a `timeline.<id>` without one is refused, and so is a node with dates on any other sheet (NODE).
    timeline = timeline_dates(sheet, bundle)
    dated: dict[str, dict[str, set[str]]] = {}
    if sheet.partition(".")[0] not in SHEETS:
        problems.append(f"{sheet}: a sheet of a kind the checker does not know")
    if sheet.startswith("timeline.") and timeline is None:
        problems.append(f"{sheet}: no Timeline of the bundle has this sheet")
    if timeline is not None:
        wanted = {f"{kind}/{i}" for kind, i in once if timeline["rows"] in chain(bundle, kind)}
        problems += [f"{sheet}: node {i} is no row of the Timeline: no element of {timeline['rows']} the role reads"
                     for i in sorted(set(nodes) - wanted)]
        problems += [f"{sheet}: row {i} is missing: the role reads it" for i in sorted(wanted - set(nodes))]
        if lines:
            problems.append(f"{sheet}: a Timeline holds no lines, the layout has {len(lines)}")
        for relation in timeline["dates"]:
            by = dated.setdefault(relation, {})
            for parts in read.get(relation, set()):
                if len(parts) == 2:
                    by.setdefault(parts[0], set()).add(parts[1])
    # A Nest is parts and nothing else: every element of its first level the role reads, every element of a
    # later level whose container (the role's row of the level's arrow) is a part, and every element whose
    # container is unknown, apart, with its own parts. In a tile a part holds its container and its states
    # (`_nest_part`). No line, no stub, no placeholder.
    nest = nest_levels(sheet, bundle)
    nested: dict[str, object] = {}
    part_table: dict[str, str] = {}
    part_states: dict[str, dict[str, list]] = {}
    stateless: dict[str, object] = {}
    if sheet.partition(".")[0] == "nest" and nest is None:
        problems.append(f"{sheet}: no Nest of the bundle has this sheet")
    if nest is not None:
        nested, twice = nest_parts(nest, read, once, bundle, role.full)
        problems += [f"{sheet}: {p}" for p in twice]
        problems += [f"{sheet}: node {i} is no part of this Nest" for i in sorted(set(nodes) - set(nested))]
        problems += [f"{sheet}: part {i} is missing: the role reads it" for i in sorted(set(nested) - set(nodes))]
        if lines:
            problems.append(f"{sheet}: a Nest holds no lines, the layout has {len(lines)}")
        for node_id in nested:
            level = next(nest["kinds"].index(k) for k in chain(bundle, node_id.partition("/")[0]) if k in nest["kinds"])
            part_table[node_id] = nest["tables"][level]
        for view, (relation, part, shown) in nest["views"].items():
            stateless[view] = [] if lacking(relation, nest["relations"][view], True, role.full) == "none" else APART
            by_part = part_states.setdefault(view, {})
            for row in read.get(relation, set()):
                if len(row) > max([part, *shown]):
                    by_part.setdefault(row[part], []).append([row[c] for c in shown])
            for rows_of_part in by_part.values():
                rows_of_part.sort()
    element = lambda node_id: shows.get(node_id, node_id)
    for node_id in sorted(nodes):
        if node_id.startswith("stub/"):
            if node_id not in stubs:
                problems.append(f"{sheet}: stub {node_id} is a stub the island levels do not give")
        elif not _readable(element(node_id), readable):
            problems.append(f"{sheet}: node {node_id} is no row the role reads")
        elif not _placeholder(node_id) and tuple(element(node_id).split("/", 1)) not in once:
            problems.append(f"{sheet}: node {node_id} is not its element at its most specific kind")
    for edge_id, e in sorted(lines.items()):
        if e.get("source") not in nodes or e.get("target") not in nodes:
            problems.append(f"{sheet}: line {edge_id} does not join two nodes of the layout")

    # Counts by centre, per tile of each level, recomputed from the layout (rows only: they are valid).
    last = levels - 1
    def leaf(x, y, w, h) -> tuple[int, int]:
        return int((x + w / 2) // tile), int((y + h / 2) // tile)

    centres = [(x + w / 2, y + h / 2, (z_index(*leaf(x, y, w, h)), y, x, i))
               for i, (x, y, w, h) in nodes.items() if not _placeholder(i)]
    drawn: set[tuple[str, str]] = set()

    # Per level, the centres by the cluster that holds them: each node once per level, never per cluster.
    buckets: dict[int, dict[tuple[int, int], list]] = {}

    def count(level: int, cx: int, cy: int) -> tuple[int, str | None, str | None]:
        if level not in buckets:
            side = tile * fanout ** (last - level)
            by: dict[tuple[int, int], list] = {}
            for x, y, order in centres:
                by.setdefault((int(x // side), int(y // side)), []).append(order)
            buckets[level] = {at: sorted(v) for at, v in by.items()}
        inside = buckets[level].get((cx, cy), [])
        return len(inside), inside[0][3] if inside else None, inside[-1][3] if inside else None

    def guide(c: dict, which: str, want: str | None) -> list[str]:
        e = c.get(which)
        where = f"{sheet}: cluster {c['x']}_{c['y']}"
        if e is None:
            return [] if want is None else [f"{where} has no {which} element, the layout {want}"]
        if not isinstance(e, dict) or set(e) - {"id", "name"} or e.get("id") != want:
            return [f"{where} names {e} as its {which} element, the layout {want}"]
        if "name" in e and not _name(element(want).partition("/")[2], e["name"], read):
            return [f"{where} shows a name for {want} that is no rows the role reads: {e['name']}"]
        return []

    lanes: dict[str, str] = {}  # node id: the key of its lane, from the cell it holds
    bands: dict[str, tuple] = {}  # band key: (axis, from, to, hatched, name), the same in every tile
    placed: list[tuple] = []  # (tile, node id, box, its bands by key) of every node with a lane, on the last level
    member: dict[str, tuple[str, str]] = {}  # node id: (target kind, group id), from the cell it holds
    boxes: dict[str, tuple] = {}  # group node id: (x, y, width, height, name), the same in every tile
    grouped: list[tuple] = []  # (tile, node id, box, its groups by id) of every node in a group, on the last level
    reached: set[str] = set()
    todo = [(root, None)]
    while todo:
        path, sha = todo.pop()
        data = tiles.get(path)
        if data is None:
            problems.append(f"{sheet}: tile {path} is missing")
            continue
        if sha is not None and hashlib.sha256(data).hexdigest() != sha:
            problems.append(f"{sheet}: tile {path} does not have the sha256 its parent names")
        reached.add(path)
        t = json.loads(data)
        if t.get("sheet") != sheet or f"{sheet}/{t.get('level')}/{t.get('x')}_{t.get('y')}.json" != path:
            problems.append(f"{sheet}: tile {path} says it is another tile")
        for c in t.get("clusters", []):
            n, first, last_one = count(t["level"] + 1, c["x"], c["y"])
            problems += guide(c, "first", first) + guide(c, "last", last_one)
            if c["count"] != n or c["statuses"] != ([{"status": "valid", "count": n}] if n else []):
                problems.append(f"{sheet}: cluster {t['level'] + 1}/{c['x']}_{c['y']} counts {c['count']} {c['statuses']}, the layout {n}")
            todo.append((f"{sheet}/{t['level'] + 1}/{c['x']}_{c['y']}.json", c["sha256"]))
        shown = t.get("bands", [])
        for b in shown:
            if not isinstance(b, dict) or set(b) - BAND or b.get("axis") not in ("x", "y") or \
                    b.get("hatched", False) != (b.get("key") == UNKNOWN_LANE):
                problems.append(f"{sheet}: tile {path} holds a lane that is no band: {b}")
                continue
            facts = (b["axis"], b["from"], b["to"], b.get("hatched", False), b.get("name"))
            if bands.setdefault(b["key"], facts) != facts:
                warnings.append(f"{sheet}: lane {b['key']} is not the same in every tile")
            target = re.match(r"^kind:([^:]+):(.*)$", b["key"], re.S)
            if "name" in b and not (target and _name(target.group(2), b["name"], read)):
                problems.append(f"{sheet}: lane {b['key']} has a name that is no rows the role reads: {b['name']}")
        held = t.get("groups", [])
        for g in held:
            if not isinstance(g, dict) or set(g) - GROUP or not {"id", "x", "y", "width", "height"} <= set(g) or "/" not in str(g["id"]):
                problems.append(f"{sheet}: tile {path} holds a group that is no box: {g}")
                continue
            if tuple(g["id"].split("/", 1)) not in once:
                problems.append(f"{sheet}: group {g['id']} is no element the role reads at its most specific kind")
            if "name" in g and not _name(g["id"].partition("/")[2], g["name"], read):
                problems.append(f"{sheet}: group {g['id']} has a name that is no rows the role reads: {g['name']}")
            facts = (g["x"], g["y"], g["width"], g["height"], json.dumps(g.get("name"), sort_keys=True))
            if boxes.setdefault(g["id"], facts) != facts:
                warnings.append(f"{sheet}: group {g['id']} is not the same in every tile")
        spans = sorted((b["from"], b["to"]) for b in shown if isinstance(b, dict) and "from" in b)
        if any(a[1] > z[0] for a, z in zip(spans, spans[1:])) or len({b.get("axis") for b in shown}) > 1:
            warnings.append(f"{sheet}: tile {path} holds lanes that cross")
        # Only the last level holds nodes and lines (tiles.ts, Tile); a tile above it that holds one is refused, so
        # no node escapes the checks of its lane and group cells, which hold there.
        if t.get("level") != last and (t.get("nodes") or t.get("edges")):
            problems.append(f"{sheet}: tile {path} holds nodes or lines above the last level")
        for n in t.get("nodes", []):
            if nest is not None:  # before the node's group is read as a box: a part that stands apart has none
                problems += [f"{sheet}: tile {path}: {p}" for p in _nest_part(n, nested, part_table, part_states, stateless)]
                n = {k: v for k, v in n.items() if k != "states" and (k, v) != ("group", APART)}
            if t.get("level") == last:
                drawn.add((path, n["id"]))
                if "lane" in n and not _placeholder(n["id"]):
                    # A Matrix's head stands in the lane of the element it shows (a Board's column, docs/gui.md).
                    key = lane_key(n.get("of", n["id"]), n["lane"], read, bundle)
                    if key is None:
                        problems.append(f"{sheet}: node {n['id']} stands in a lane that is no row the role reads: {n['lane']}")
                    else:
                        lanes[n["id"]] = key
                        placed.append((path, n["id"], [n["x"], n["y"], n["width"], n["height"]], {b.get("key"): b for b in shown}))
                if "group" in n and not _placeholder(n["id"]):
                    of = group_of(n["id"], n["group"], read, bundle)
                    if of is None:
                        problems.append(f"{sheet}: node {n['id']} stands in a group that is no row the role reads: {n['group']}")
                    else:
                        member[n["id"]] = of
                        grouped.append((path, n["id"], [n["x"], n["y"], n["width"], n["height"]], {g.get("id"): g for g in held if isinstance(g, dict)}))
            if n["id"] not in nodes or nodes[n["id"]] != [n["x"], n["y"], n["width"], n["height"]]:
                problems.append(f"{sheet}: tile {path} shows node {n['id']} not as laid out")
            if n.get("of") != shows.get(n["id"]):
                problems.append(f"{sheet}: tile {path} shows node {n['id']} as another element than the layout")
            if timeline is not None:
                problems += [f"{sheet}: tile {path}: {p}" for p in _timeline_row(n, timeline, dated, role.full)]
                n = {k: v for k, v in n.items() if k != "dates"}
            problems += [f"{sheet}: tile {path}: {p}" for p in _node(n, read, stubs, bundle)]
        for e in t.get("edges", []):
            was = lines.get(e.get("id"))
            if not was or (was["source"], was["target"], was["points"]) != (e.get("source"), e.get("target"), e.get("points")):
                problems.append(f"{sheet}: tile {path} shows line {e.get('id')} not as laid out")
            problems += [f"{sheet}: tile {path}: {p}" for p in _edge(e, read, bundle, shows)]
            if matrix is not None:
                problems += [f"{sheet}: tile {path}: {p}" for p in _cell(e, matrix, shows, bundle)]
        if path == root and not t.get("clusters"):
            n = sum(1 for x in t.get("nodes", []) if not _placeholder(x["id"]))
            if n != len(centres):
                problems.append(f"{sheet}: the root shows {n} nodes, the layout has {len(centres)}")
    for node_id, box in sorted(nodes.items()):
        lx, ly = leaf(*box)
        if (f"{sheet}/{last}/{lx}_{ly}.json", node_id) not in drawn:
            problems.append(f"{sheet}: node {node_id} is drawn in no tile, not in the one that holds its centre")
    # Lanes: a band is the lane of a node; a node lies inside the band of its lane, in its own tile.
    for key in sorted(set(bands) - set(lanes.values())):
        problems.append(f"{sheet}: lane {key} is the lane of no node the role reads")
    for path, node_id, (x, y, w, h), here in placed:
        b = here.get(lanes[node_id])
        start, size = (x, w) if b and b["axis"] == "x" else (y, h)
        if not b or start < b["from"] or start + size > b["to"]:
            warnings.append(f"{sheet}: node {node_id} lies outside its lane {lanes[node_id]} in tile {path}")
    # Groups: a box is the group of a node (its id an element of the arrow's target kind or below); a member lies
    # inside its box, in its own tile.
    def of_box(group_id: str) -> set[tuple[str, str]]:
        kind, _, i = group_id.partition("/")
        return {(k, i) for k in chain(bundle, kind)}
    for group_id in sorted(boxes):
        if not of_box(group_id) & set(member.values()):
            problems.append(f"{sheet}: group {group_id} is the group of no node the role reads")
    for path, node_id, (x, y, w, h), here in grouped:
        box = next((g for i, g in sorted(here.items()) if member[node_id] in of_box(i)), None)
        if not box or x < box["x"] or y < box["y"] or x + w > box["x"] + box["width"] or y + h > box["y"] + box["height"]:
            warnings.append(f"{sheet}: node {node_id} lies outside its group in tile {path}")
    # On a Board the lanes are the columns, so the head of a row stands in none.
    laned = [i for i in nodes if not _placeholder(i) and not i.startswith("stub/") and not (matrix is not None and i.startswith("rows/"))]
    if lanes and len(lanes) != len(laned):
        warnings.append(f"{sheet}: some nodes stand in a lane, others in none")
    unreached = sorted(set(tiles) - reached)
    if unreached:
        problems.append(f"{sheet}: tiles not reached from the root: {', '.join(unreached[:3])}")
    return problems


ISLANDS = "rezono.islands/1"


class IslandPlan(NamedTuple):
    levels: dict[str, dict]
    """By key."""
    maps: dict[str, set[str]]
    """Per Map sheet, its elements as node ids."""
    stubs: dict[str, dict[str, dict]]
    """Per Map sheet, what each stub shows, by its node id."""
    stub_lines: dict[str, set[tuple[str, str, str]]]
    """Per Map sheet, its lines to stubs: (line id, source, stub)."""


def islands(snapshots: dict[str, bytes], bundle: dict) -> tuple[dict[str, dict], dict[str, set[str]]]:
    """The island levels and the elements of each Map (`island_plan`)."""
    plan = island_plan(snapshots, bundle)
    return plan.levels, plan.maps


def island_plan(snapshots: dict[str, bytes], bundle: dict, role: Role | None = None) -> IslandPlan:
    """The island levels of the overview (docs/gui.md, Zoom: islands by meaning), recounted from the role's
    rows and the bundle's kinds and parents alone: ({level key: level}, {map sheet: its elements as node ids}).

    Level 0 (`root`) has an island per root kind with an element the role reads; a kind with such subkinds
    opens a level of them, plus an island `o.<kind>` of its own elements of no subkind; any other island opens
    its Map, the sheet `map.<key>`. A level of one island is skipped: a single root island that opens a level
    makes that level level 0, and one that opens a Map makes that Map the sheet `map`, with no level 0. Every element counts once, at its most specific kind; every readable
    element is valid, as on the Map. A line of a level is the arrow rows from an element of one of its islands
    to one of another, per arrow: the arrow is a slot of the source's kind or a supertype, and its end is the
    element the role reads at the arrow's target or a kind below it.

    On a Map, such a line to an element of another island's Map ends at a stub that opens that island, by its
    path of steps from level 0: one per island and arrow, counting its lines, or, on a Map with no line
    between two of its elements (laid out as an index), one per element and island and arrow. A line from an
    element of another island's Map into one of this Map starts at a stub of lines coming in (`direction: in`,
    `stub/in/<island>/<arrow>`, on an index `stub/in/<element>/<island>/<arrow>`), one line per stub and element.
    """
    role = role or Role(snapshots, bundle)
    read, once = role.read, role.once
    kinds = [k["id"] for k in bundle.get("kinds", [])]
    parent = {k["id"]: k.get("parent") for k in bundle.get("kinds", [])}
    children = {k: [c for c in kinds if parent[c] == k] for k in kinds}
    own = {k: {f"{kind}/{i}" for kind, i in once if kind == k} for k in kinds}

    def below(k: str) -> set[str]:
        return own[k].union(*(below(c) for c in children[k]))

    def members(key: str) -> set[str]:
        return own[key[2:]] if key.startswith("o.") else below(key[2:])

    ids: dict[str, list[str]] = {}
    for kind, i in once:
        ids.setdefault(i, []).append(kind)
    lines = []
    for arrow in bundle.get("arrows", []):
        table, source, target = arrow["table"], arrow["kind"], arrow["target"]
        for key in read.get(table, set()):
            if len(key) != 2:
                continue
            frm = [k for k in ids.get(key[0], []) if source in chain(bundle, k)]
            to = [k for k in ids.get(key[1], []) if target in chain(bundle, k)]
            if frm and to:
                lines.append((f"{frm[0]}/{key[0]}", f"{to[0]}/{key[1]}", table))

    levels: dict[str, dict] = {}
    maps: dict[str, set[str]] = {}

    def entry(key: str, kind: str, opens: dict) -> dict:
        n = len(members(key))
        return {"key": key, "kind": kind, "count": n, "statuses": [{"status": "valid", "count": n}] if n else [], "opens": opens}

    def level(key: str, entries: list[dict]) -> dict:
        owner = {node: e["key"] for e in entries for node in members(e["key"])}
        counts: dict[tuple[str, str, str], int] = {}
        for frm, to, arrow in lines:
            a, b = owner.get(frm), owner.get(to)
            if a and b and a != b:
                counts[(a, b, arrow)] = counts.get((a, b, arrow), 0) + 1
        return {"format": ISLANDS, "key": key, "islands": entries,
                "lines": [{"from": a, "to": b, "arrow": arrow, "count": n} for (a, b, arrow), n in sorted(counts.items())]}

    def opens_map(key: str, kind: str) -> dict:
        maps[f"map.{key}"] = members(key)
        return entry(key, kind, {"map": f"map.{key}"})

    def island(kind: str) -> dict:
        kids = [c for c in children[kind] if below(c)]
        if not kids:
            return opens_map(f"k.{kind}", kind)
        entries = [island(c) for c in kids]
        if own[kind]:
            entries.append(opens_map(f"o.{kind}", kind))
        if len(entries) == 1:
            return entries[0]
        levels[f"k.{kind}"] = level(f"k.{kind}", entries)
        return entry(f"k.{kind}", kind, {"level": f"k.{kind}"})

    roots = [island(k) for k in kinds if not parent[k] and below(k)]
    key_of = {sheet: sheet[len("map."):] for sheet in maps}
    if len(roots) == 1 and "level" in roots[0]["opens"]:
        levels["root"] = dict(levels.pop(roots[0]["key"]), key="root")
    elif len(roots) == 1:
        key_of["map"] = key_of.pop(roots[0]["opens"]["map"])
        maps["map"] = maps.pop(roots[0]["opens"]["map"])
    else:
        levels["root"] = level("root", roots)

    path_of = {sheet: [] for sheet in maps}

    def walk(key: str, path: list[str]) -> None:
        for e in levels[key]["islands"]:
            if "level" in e["opens"]:
                walk(e["opens"]["level"], [*path, e["key"]])
            else:
                path_of[e["opens"]["map"]] = [*path, e["key"]]

    if "root" in levels:
        walk("root", [])
    sheet_of = {node: sheet for sheet, nodes in maps.items() for node in nodes}
    stubs: dict[str, dict[str, dict]] = {sheet: {} for sheet in maps}
    stub_lines: dict[str, set[tuple[str, str, str]]] = {sheet: set() for sheet in maps}
    for sheet, nodes in maps.items():
        index = not any(frm in nodes and to in nodes for frm, to, _ in lines)
        for frm, to, arrow in sorted(lines):
            other = sheet_of.get(to)
            if frm not in nodes or other in (None, sheet):
                continue
            stub = f"stub/{frm}/{key_of[other]}/{arrow}" if index else f"stub/{key_of[other]}/{arrow}"
            shown = stubs[sheet].setdefault(stub, {"island": key_of[other], "path": path_of[other], "arrow": arrow, "count": 0})
            shown["count"] += 1
            stub_lines[sheet].add((stub_line(frm, arrow, stub, bundle), frm, stub))
        # A line from another island's Map into this one: a stub of lines coming in, before its element.
        for frm, to, arrow in sorted(lines):
            other = sheet_of.get(frm)
            if to not in nodes or other in (None, sheet):
                continue
            stub = f"stub/in/{to}/{key_of[other]}/{arrow}" if index else f"stub/in/{key_of[other]}/{arrow}"
            shown = stubs[sheet].setdefault(stub, {"island": key_of[other], "path": path_of[other], "arrow": arrow, "count": 0,
                                                   "direction": "in"})
            shown["count"] += 1
            stub_lines[sheet].add((f"{stub}->{arrow}->{to}", stub, to))
    return IslandPlan(levels, maps, stubs, stub_lines)


def check_islands(snapshots: dict[str, bytes], bundle: dict, levels: dict[str, bytes], layouts: dict[str, bytes],
                  role: Role | None = None) -> list[str]:
    """Problems with a role's island levels and the Maps they open: every level is exactly the one the role's
    rows give (islands, counts, statuses, what each opens, the bundled lines and their counts), there is no
    other level, and every island's Map is a sheet whose layout draws exactly the island's elements (its unknown
    and screened ends aside). `levels` by key, `layouts` the whole layout of every sheet, by sheet."""
    want, maps, stubs, stub_lines = (role or Role(snapshots, bundle)).plan
    problems = []
    for key in sorted(set(want) | set(levels)):
        if key not in levels:
            problems.append(f"islands: level {key} is missing")
        elif key not in want:
            problems.append(f"islands: level {key} is no level the role's rows give")
        elif json.loads(levels[key]) != want[key]:
            problems.append(f"islands: level {key} is not what the role's rows give")
    for sheet in sorted(set(maps) | set(layouts)):
        if sheet not in layouts:
            problems.append(f"islands: the Map {sheet} is missing")
        elif sheet not in maps:
            problems.append(f"islands: {sheet} is the Map of no island")
        else:
            whole = json.loads(layouts[sheet])
            drawn = {i for i in whole.get("nodes", {}) if not _placeholder(i)}
            if drawn != maps[sheet]:
                problems.append(f"islands: {sheet} draws {len(drawn)} elements, the island holds {len(maps[sheet])}")
            if {i for i in whole.get("nodes", {}) if i.startswith("stub/")} != set(stubs[sheet]):
                problems.append(f"islands: {sheet} does not have the stubs its lines to other islands give")
            to_stubs = {(i, e.get("source"), e.get("target")) for i, e in whole.get("edges", {}).items()
                        if str(e.get("target")).startswith("stub/") or str(e.get("source")).startswith("stub/")}
            if to_stubs != stub_lines[sheet]:
                problems.append(f"islands: {sheet} draws {len(to_stubs)} lines to stubs, its lines to other islands are {len(stub_lines[sheet])}")
    return problems

