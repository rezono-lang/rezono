"""The proof graph of a role as key-range pieces (docs/gui.md, "The proof graph as relations").

Per main manifest and filtered role, made with the views (rezono_publisher.views) and listed in the same view
index. The role's chosen witnesses become the relation `step` (rezono_compiler.trace.steps), published as
three trees per relation:

    proof/witness/<c_relation>   rows: the chosen Witness or CalcWitness, unchanged, by conclusion key
    proof/back/<c_relation>      rows: [c_key, how, position, p_relation, p_key]
    proof/forward/<p_relation>   rows: [p_key, c_relation, c_key, how, position]

A `contributes` row of a `sum`, `min` or `max` has one element more, last in both trees: what its row gives
the aggregate, the value text the witness's `contributors_sha256` is taken over (trace.steps, `valued`).

The same tree carries the role's snapshots, one per relation, for a row or a key prefix (O(page), step 3):

    rows/<relation>              rows: the snapshot's records, unchanged, by key
    inverse/<relation>           the same, by the key reversed: of a relation with two columns only (an
                                 arrow `k__a(id, target)`: the rows that point to a target)

And the role's source entries, for the base rows on a page of an answer (rezono_publisher.sources):

    sources/<relation>           rows: {"key", "sources"[, "reason"]}, by key: the entry without its row
                                 reference (sources_plan)

And for `gap` (step 6), the indexes its premise tests need (rezono_compiler.gap, the plan's `indexes`):

    index/<relation>/<bound>     the same records, by the bound columns first (`<bound>`: their positions,
                                 joined by `-`), then the rest in order; the tree is named `index:<b>,…`.
                                 Not for a pattern the inverse tree already serves (two columns, [1]).

Keys are lists, ordered element by element: text by its UTF-8 bytes (Python orders str by code point,
which is the same order), a number by its value, a list before every longer list it begins. A leaf holds
rows in order, at most PIECE bytes; a page above it names at most FANOUT children with the first
and last sort key of each and the sha256 of its bytes, up to one root per tree and relation. So a lookup
reads one page per level and the leaves it needs, each bounded, and the gate checks each piece from the one
above it, down from the view index. The checker rebuilds `step` on its own (rezono_checker.proof).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from rezono_canon import canonical_sha256
from rezono_compiler import rules as ir
from rezono_compiler import trace

FORMAT = "rezono.proof/1"
# 2: the calculation witnesses are in the trees too. 3: a `contributes` row may carry its value last:
# such a row is longer than a page cursor on it, so a reader of format 2 must not read these trees.
INDEX = "rezono.proof-index/3"
PIECE = 64 * 1024  # bytes per piece, at most
FANOUT = 128  # children per page, at most
TREES = ("witness", "back", "forward")


class TooLarge(ValueError):
    """One row does not fit in a piece."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sort_key(tree: str, row) -> list:
    """The key a tree is ordered by: a witness by its conclusion key, a snapshot row, a difference entry or a
    source entry by its key, an edge by itself."""
    if tree == "witness":
        return [row["conclusion"]["key"]]
    if tree == "inverse":
        return row["key"][::-1]
    if tree.startswith("index:"):
        return permuted(row["key"], bound_of(tree))
    return row["key"] if tree in ("rows", "difference", "sources") else row


def bound_of(tree: str) -> list[int]:
    """The bound positions an index tree is named by: `index:1,0` -> [1, 0]."""
    return [int(x) for x in tree.removeprefix("index:").split(",")]


def index_name(bound) -> str:
    return "index:" + ",".join(str(i) for i in bound)


def permuted(key: list, bound) -> list:
    """A row's columns with the bound ones first, in their order, then the rest in order."""
    return [key[i] for i in bound] + [v for i, v in enumerate(key) if i not in bound]


def served_by_inverse(rs: list, bound) -> bool:
    """True if the inverse tree already orders the rows this way: two columns, the second bound."""
    return list(bound) == [1] and all(len(r["key"]) == 2 for r in rs)


def rows(witnesses: list[dict], steps: list[tuple]) -> dict:
    """{tree: {relation: rows in order}}."""
    out = {t: defaultdict(list) for t in TREES}
    for w in witnesses:
        out["witness"][w["conclusion"]["relation"]].append(w)
    for c_rel, c_key, p_rel, p_key, how, pos, *value in steps:  # the value last, where an edge has one
        out["back"][c_rel].append([c_key, how, pos, p_rel, p_key, *value])
        out["forward"][p_rel].append([p_key, c_rel, c_key, how, pos, *value])
    return {t: {rel: sorted(rs, key=lambda r: sort_key(t, r)) for rel, rs in sorted(by.items())}
            for t, by in out.items()}


def _pack(items: list, make, limit: int, fanout: int | None) -> list[tuple[list, bytes]]:
    """Cut items in order into pieces of at most `limit` bytes (and `fanout` items): [(items, bytes)].

    The size of a piece is counted, not measured again per item: compact JSON is the empty piece, every
    item's own bytes and a comma between two items."""
    empty = len(make([]))
    out, cur, size = [], [], empty
    for item in items:
        n = len(dumps(item))
        if empty + n > limit:
            raise TooLarge(f"one entry is larger than a piece ({limit} bytes)")
        if cur and ((fanout and len(cur) == fanout) or size + 1 + n > limit):
            out.append((cur, make(cur)))
            cur, size = [], empty
        size += n + (1 if cur else 0)
        cur.append(item)
    if cur:
        out.append((cur, make(cur)))
    return out


def tree(tree_name: str, relation: str, rs: list, at, limit: int = PIECE, fanout: int = FANOUT):
    """One tree: (root path, levels, {path: bytes}). `at(level, n)` is the path of a piece."""
    head = {"format": FORMAT, "tree": tree_name, "relation": relation}
    files, level = {}, 0
    pieces = _pack(rs, lambda xs: dumps(head | {"level": 0, "rows": xs}), limit, None)
    while True:
        refs = []
        for n, (items, data) in enumerate(pieces):
            path = at(level, n)
            files[path] = data
            first = sort_key(tree_name, items[0]) if level == 0 else items[0]["first"]
            last = sort_key(tree_name, items[-1]) if level == 0 else items[-1]["last"]
            refs.append({"first": first, "last": last, "file": path, "sha256": sha256(data)})
        if len(refs) == 1:
            return refs[0]["file"], level + 1, files
        level += 1
        pieces = _pack(refs, lambda xs: dumps(head | {"level": level, "children": xs}), limit, fanout)
        if len(pieces) >= len(refs):  # a page holds one child only: the keys are too long for this piece size
            raise TooLarge(f"{tree_name}/{relation}: the pages of level {level} do not hold two children each "
                           f"within {limit} bytes; a sort key is too long")


def calc_steps(calc_witnesses: list[dict]) -> list[tuple]:
    """The `step` rows of calculation witnesses: one per premise, `positive`, at its place in the
    witness's `premises`. Its `reads` are relations, not rows: no step."""
    return [(w["conclusion"]["relation"], w["conclusion"]["key"], p["relation"], p["key"], "positive", i)
            for w in calc_witnesses for i, p in enumerate(w.get("premises", ()))]


def engine_rows(prog, relation: str, snapshot: bytes) -> list[tuple]:
    """A snapshot's records as the engine's rows, which `trace.steps` reads: the key columns, then the value
    columns in the relation's order, each a known cell's text. A cell that is missing or not known is None,
    as the checker reads a missing column as unknown: `trace.steps` refuses to state a contribution from it."""
    values = [c.name for c in prog.relations[relation].values] if relation in prog.relations else []

    def cell(v: dict):
        return v.get("value", v.get("minor_units")) if v.get("state") == "known" else None

    return [tuple(r["key"]) + tuple(cell(r.get("values", {}).get(c, {})) for c in values) for r in json.loads(snapshot)]


def _with_iri(w: dict, base_iri: str | None) -> dict:
    if not base_iri:
        return w
    raw = {k: v for k, v in w.items() if k != "iri"}
    return {**raw, "iri": f"{base_iri}witness/{canonical_sha256(raw)}"}


def plan(rules_doc: dict | None, sees: dict, snapshots: dict, base: str, limit: int = PIECE, fanout: int = FANOUT,
         *, base_iri: str | None = None):
    """The pieces of one role and the `proof` part of its view index.

    `rules_doc` is the manifest's rule IR (None without rules), `sees` the role's witness file, `snapshots`
    the role's snapshot bytes per relation and `base` the key prefix of the role's views
    (`<pack>/<manifest>/<role>/views`). The rule witnesses and the calculation witnesses go into the same
    trees: a conclusion is a row of one relation, derived by a rule or calculated, never both.
    Returns ([(key, bytes)], {tree: {relation: {"file", "sha256", "levels"}}})."""
    witnesses, calc = sees["witnesses"], sees.get("calc_witnesses", [])
    step_rows = calc_steps(calc)
    if witnesses:
        prog = ir.load(rules_doc)
        step_rows += trace.steps(prog, witnesses, {rel: engine_rows(prog, rel, b) for rel, b in snapshots.items()}, valued=True)
    stamped = [_with_iri(w, base_iri) for w in witnesses]
    by_tree = rows(stamped + calc, step_rows)
    pieces, roots = [], {t: {} for t in TREES}
    for t in TREES:
        for rel, rs in by_tree[t].items():
            root, levels, files = tree(t, rel, rs, lambda lv, n: f"proof/{t}/{rel}/{lv}/{n}.json", limit, fanout)
            pieces += [(f"{base}/{path}", b) for path, b in sorted(files.items())]
            roots[t][rel] = {"file": root, "sha256": sha256(files[root]), "levels": levels}
    return pieces, roots


def rows_plan(snapshots: dict, base: str, limit: int = PIECE, fanout: int = FANOUT):
    """The role's snapshots as key-range trees: ([(key, bytes)], {relation: root}, {relation: inverse root}).

    A relation without rows has no tree; its root is {"count": 0}, so the gate tells an empty relation from
    one the role does not read. Every other root is {"file", "sha256", "levels", "count"}. A relation whose
    keys have two columns also gets the inverse tree, {"file", "sha256", "levels"}."""
    pieces, roots, inverse = [], {}, {}
    for rel in sorted(snapshots):
        rs = json.loads(snapshots[rel])
        if not rs:
            roots[rel] = {"count": 0}
            continue
        for name in ("rows", "inverse") if all(len(r["key"]) == 2 for r in rs) else ("rows",):
            ordered = sorted(rs, key=lambda r: sort_key(name, r))
            root, levels, files = tree(name, rel, ordered, lambda lv, n: f"{name}/{rel}/{lv}/{n}.json", limit, fanout)
            pieces += [(f"{base}/{path}", b) for path, b in sorted(files.items())]
            named = {"file": root, "sha256": sha256(files[root]), "levels": levels}
            if name == "rows":
                roots[rel] = named | {"count": len(rs)}
            else:
                inverse[rel] = named
    return pieces, roots, inverse


def index_plan(gap_plan: dict, snapshots: dict, base: str, limit: int = PIECE, fanout: int = FANOUT):
    """The indexes of `gap` for one role: ([(key, bytes)], [entry]). Per pattern of the plan's `indexes`
    over a relation the role has rows of, one entry {"relation", "bound"} with either its own tree
    ({"file", "sha256", "levels"}) or {"tree": "inverse"} where that tree already serves it. A relation the
    role does not read, or has no rows of, gets no entry: its `rows` root says which (docs/gui.md, "gap")."""
    pieces, entries = [], []
    for idx in gap_plan["indexes"]:
        rel, bound = idx["relation"], idx["bound"]
        if rel not in snapshots:
            continue
        rs = json.loads(snapshots[rel])
        if not rs:
            continue
        if served_by_inverse(rs, bound):
            entries.append({"relation": rel, "bound": bound, "tree": "inverse"})
            continue
        name = index_name(bound)
        ordered = sorted(rs, key=lambda r: sort_key(name, r))
        at = "-".join(str(i) for i in bound)
        root, levels, files = tree(name, rel, ordered, lambda lv, n: f"index/{rel}/{at}/{lv}/{n}.json", limit, fanout)
        pieces += [(f"{base}/{path}", b) for path, b in sorted(files.items())]
        entries.append({"relation": rel, "bound": bound, "file": root, "sha256": sha256(files[root]), "levels": levels})
    return pieces, entries


def entry_row(entry: dict) -> dict:
    """A role's source entry (rezono_publisher.sources) as a leaf row of its relation's `sources` tree: the
    entry without its row reference, which the tree (relation) and the key (its text parts) give."""
    return {"key": json.loads(entry["row"]["key"])} | {k: v for k, v in entry.items() if k != "row"}


def sources_plan(entries: list[dict], base: str, limit: int = PIECE, fanout: int = FANOUT):
    """The role's source entries as key-range trees, one per relation it has entries of: the sources of
    the base rows on one page of an answer are then read with one lookup per row, never the whole set.

        sources/<relation>           rows: {"key", "sources"[, "reason"]}, by key

    Returns ([(key, bytes)], {relation: {"file", "sha256", "levels"}}). A relation without entries has no tree."""
    by: dict[str, list] = defaultdict(list)
    for e in entries:
        by[e["row"]["relation"]].append(entry_row(e))
    pieces, roots = [], {}
    for rel, rs in sorted(by.items()):
        ordered = sorted(rs, key=lambda r: sort_key("sources", r))
        root, levels, files = tree("sources", rel, ordered, lambda lv, n: f"sources/{rel}/{lv}/{n}.json", limit, fanout)
        pieces += [(f"{base}/{path}", b) for path, b in sorted(files.items())]
        roots[rel] = {"file": root, "sha256": sha256(files[root]), "levels": levels}
    return pieces, roots
