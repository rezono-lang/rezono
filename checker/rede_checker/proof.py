"""Check the proof pieces of one role (decision R10) against the role's witnesses and snapshots.

The publisher writes the role's proof graph as key-range trees (rede_publisher.proof). This module trusts
none of it: it rebuilds the relation `step` on its own, from the rule definitions (premise positions in
rule-body order, polarities from the rule), the calculation witnesses (each premise, positive, at its index)
and the role's snapshots (an aggregate's group: every row that
matches the fixed positions of the aggregate atom under the witness's bindings), and requires every tree to
hold exactly those rows, in order, in pieces within the limits, each named by the sha256 of its bytes, with
no piece left over.

A `contributes` edge of a `sum`, `min` or `max` carries what its row gives the aggregate (RV-C09): the cell
the aggregate reads, as the value text the witness's `contributors_sha256` is taken over. It is read here from
the role's snapshot, as the proof check reads it (evaluate.cells), so the edges of an aggregate are exactly
the contributors that check hashes and folds: a published contribution that differs, is missing, or stands on
a `count` edge or a premise is not the role's proof graph.

The same trees carry the role's snapshots (`rows/<relation>`, O(page) step 3): check_rows requires each to hold
exactly its snapshot's records, in key order (element by element, text by its UTF-8 bytes; the check sorts
on the encoded bytes itself, not on the publisher's order).

And the indexes of `gap` (step 6): check_indexes requires the plan's `indexes` to be exactly the lookups of
its schedules whose bound columns are not a key prefix, and one tree per such pattern over a relation the
role has rows of, holding exactly its snapshot ordered by the bound columns first.

And the role's source entries (S25, `sources/<relation>`): check_sources requires one tree per relation the
role has entries of, holding exactly those entries without their row reference, in key order.
"""

from __future__ import annotations

import hashlib
import json
import re

from .canon import encode_key, value_text
from .evaluate import cells
from .rules import load_rules
from .snapshots import read_rows, rows_of

FORMAT = "rede.proof/1"
TREES = ("witness", "back", "forward")
# A piece carries exactly its contract, nothing else: no extra field can hide data in a checked piece.
LEAF = {"format", "tree", "relation", "level", "rows"}
PAGE = {"format", "tree", "relation", "level", "children"}
CHILD = {"first", "last", "file", "sha256"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def steps(rules_doc: dict, witnesses: list[dict], rows: dict) -> set[tuple]:
    """The step rows of the witnesses: (c_relation, c_key, p_relation, p_key, how, position), and on a
    `contributes` row of a `sum`, `min` or `max` a seventh element, the value text of the row's cell."""
    rules = load_rules(rules_doc)
    groups: dict = {}
    out = set()
    for w in witnesses:
        rule = rules.get(w["rule_id"])
        if rule is None:
            raise ValueError(f"unknown rule {w['rule_id']}")
        theta = {b["variable"]: b["value"] for b in w.get("bindings", [])}

        def subst(atom):
            return tuple(theta[t] if t.startswith("?") else t for t in atom.terms)

        c = (w["conclusion"]["relation"], w["conclusion"]["key"])
        for i, b in enumerate(rule.body):
            out.add((*c, b.atom.relation, encode_key(subst(b.atom)), b.polarity, i))
        for i, spec in enumerate(rule.aggregates):
            fixed = [(pos, v) for pos, (t, v) in enumerate(zip(spec.atom.terms, subst(spec.atom))) if t != "_"]
            at = (spec.atom.relation, len(spec.atom.terms), tuple(pos for pos, _ in fixed))
            if at not in groups:
                index: dict = {}
                for k, (parts, values) in rows.get(spec.atom.relation, {}).items():
                    if len(parts) == at[1]:
                        index.setdefault(tuple(parts[pos] for pos in at[2]), []).append((k, parts, values))
                groups[at] = index
            members = groups[at].get(tuple(v for _, v in fixed), ())
            given = ([()] * len(members) if spec.function == "count"
                     else [(value_text(v),) for v in cells(spec, [(parts, values) for _, parts, values in members])])
            out |= {(*c, spec.atom.relation, k, "contributes", i, *v) for (k, _, _), v in zip(members, given)}
    return out


def calc_steps(calc_witnesses: list[dict]) -> set[tuple]:
    """The step rows of calculation witnesses (W12): each premise, `positive`, at its index in `premises`.
    Their `reads` name relations, not rows: no step."""
    out = set()
    for w in calc_witnesses:
        c = (w["conclusion"]["relation"], w["conclusion"]["key"])
        for i, p in enumerate(w.get("premises", [])):
            out.add((*c, p["relation"], p["key"], "positive", i))
    return out


def expected(witnesses: list[dict], step_rows: set[tuple]) -> dict:
    """{tree: {relation: rows in order}}, as the trees must hold them."""
    out: dict = {t: {} for t in TREES}
    for w in witnesses:
        out["witness"].setdefault(w["conclusion"]["relation"], []).append(w)
    for c_rel, c_key, p_rel, p_key, how, pos, *value in step_rows:  # the value last, where an edge has one
        out["back"].setdefault(c_rel, []).append([c_key, how, pos, p_rel, p_key, *value])
        out["forward"].setdefault(p_rel, []).append([p_key, c_rel, c_key, how, pos, *value])
    for t, by in out.items():
        for rs in by.values():
            rs.sort(key=lambda r: sort_key(t, r))
    return out


def sort_key(tree: str, row) -> list:
    if tree == "witness":
        return [row["conclusion"]["key"]]
    if tree == "inverse":
        return row["key"][::-1]
    if tree.startswith("index:"):
        return _permuted(row["key"], _bound(tree))
    return row["key"] if tree in ("rows", "difference", "sources") else row


def _bound(tree: str) -> list[int]:
    return [int(x) for x in tree.removeprefix("index:").split(",")]


def _permuted(key: list, bound: list[int]) -> list:
    return [key[i] for i in bound] + [v for i, v in enumerate(key) if i not in bound]


class _Walk:
    """Reads one role's trees down from their roots: every piece by the sha256 its parent names, within the
    limits, with exactly its contract's fields and the bounds its parent gives. Collects problems and the
    pieces it reached."""

    def __init__(self, pieces: dict, limit: int, fanout: int, problems: list):
        self.pieces, self.limit, self.fanout, self.problems = pieces, limit, fanout, problems
        self.reached: set = set()

    def read(self, path, digest, tree, relation, level):
        problems = self.problems
        if path not in self.pieces:
            problems.append(f"{path}: missing")
            return None
        data = self.pieces[path]
        self.reached.add(path)
        if hashlib.sha256(data).hexdigest() != digest:
            problems.append(f"{path}: not the piece its parent names")
            return None
        if len(data) > self.limit:
            problems.append(f"{path}: {len(data)} bytes, more than {self.limit}")
        piece = json.loads(data)
        if not isinstance(piece, dict) or set(piece) != (LEAF if level == 0 else PAGE):
            problems.append(f"{path}: fields {sorted(piece) if isinstance(piece, dict) else type(piece).__name__}, "
                            f"not exactly {sorted(LEAF if level == 0 else PAGE)}")
            return None
        head = {k: piece[k] for k in ("format", "tree", "relation", "level")}
        if head != {"format": FORMAT, "tree": tree, "relation": relation, "level": level} or type(piece["level"]) is not int:
            problems.append(f"{path}: is {head}, not level {level} of {tree}/{relation}")
            return None
        if level == 0:
            rows = piece["rows"]
            if not isinstance(rows, list) or not rows:
                problems.append(f"{path}: rows is not a list with at least one row")
                return None
            return rows
        children = piece["children"]
        if not isinstance(children, list) or not children or len(children) > self.fanout:
            problems.append(f"{path}: children is not a list of 1 to {self.fanout}")
            return None
        if not all(isinstance(ch, dict) and set(ch) == CHILD and isinstance(ch["file"], str)
                   and isinstance(ch["sha256"], str) and SHA256.match(ch["sha256"])
                   and isinstance(ch["first"], list) and isinstance(ch["last"], list) for ch in children):
            problems.append(f"{path}: a child is not exactly {sorted(CHILD)} with a file, a sha256 and two keys")
            return None
        out = []
        for ch in children:
            got = self.read(ch["file"], ch["sha256"], tree, relation, level - 1)
            if got is None:
                continue
            if not got or [sort_key(tree, got[0]), sort_key(tree, got[-1])] != [ch["first"], ch["last"]]:
                problems.append(f"{ch['file']}: its bounds are not those its parent names")
            out += got
        return out

    def root(self, name, root, keys=frozenset({"file", "sha256", "levels"})):
        """The rows of one tree down from its root, or None (a problem) if the root is not well-formed."""
        if not isinstance(root, dict) or set(root) != keys or type(root["levels"]) is not int or root["levels"] < 1:
            self.problems.append(f"{name}: the root is not exactly {sorted(keys)}")
            return None
        tree, relation = name.split("/", 1)
        return self.read(root["file"], root["sha256"], tree, relation, root["levels"] - 1)

    def unreached(self):
        for path in sorted(set(self.pieces) - self.reached):
            self.problems.append(f"{path}: a piece no tree reaches")


def check_proof(rules_doc: dict, sees: dict, snapshots: dict, pieces: dict, roots: dict, limit: int, fanout: int) -> list[str]:
    """Problems with one role's proof pieces; empty when they are exactly the role's proof graph.

    `sees` is the role's witness file, `snapshots` its snapshot bytes per relation, `pieces` the bytes per
    path and `roots` {tree: {relation: {"file", "sha256", "levels"}}}."""
    problems: list[str] = []
    rows = {rel: read_rows(b, "json") for rel, b in snapshots.items()}
    calc = sees.get("calc_witnesses", [])
    try:
        want = expected(sees["witnesses"] + calc, steps(rules_doc, sees["witnesses"], rows) | calc_steps(calc))
    except ValueError as err:
        return [f"proof: {err}"]
    walk = _Walk(pieces, limit, fanout, problems)
    for t in TREES:
        given = roots.get(t, {})
        for rel in sorted(set(given) | set(want[t])):
            if rel not in given:
                problems.append(f"{t}/{rel}: no tree")
                continue
            if rel not in want[t]:
                problems.append(f"{t}/{rel}: a tree for nothing")
                continue
            got = walk.root(f"{t}/{rel}", given[rel])
            if got is not None and got != want[t][rel]:
                problems.append(f"{t}/{rel}: the rows are not the role's proof graph")
    walk.unreached()
    return problems


def check_rows(snapshots: dict, pieces: dict, roots: dict, limit: int, fanout: int, inverse: dict | None = None) -> list[str]:
    """Problems with one role's row trees; empty when each holds exactly its snapshot.

    Per relation of the role (`snapshots`, bytes per relation) one root in `roots`: {"count": 0} for a relation
    without rows, else {"file", "sha256", "levels", "count"}, whose tree holds the snapshot's records,
    unchanged, ordered by key (element by element; text by its UTF-8 bytes), each key once. Per relation with
    rows whose keys all have two columns, and only those, one root in `inverse` ({"file", "sha256",
    "levels"}): the same records ordered by the key reversed."""
    inverse = inverse or {}
    problems: list[str] = []
    walk = _Walk(pieces, limit, fanout, problems)
    parsed: dict = {}

    def table(rel):  # each snapshot is parsed once (RV-K08)
        if rel not in parsed:
            parsed[rel] = json.loads(snapshots[rel])
        return parsed[rel]

    for rel in sorted(set(roots) | set(snapshots)):
        if rel not in snapshots:
            problems.append(f"rows/{rel}: a tree for a relation the role has no snapshot of")
            continue
        if rel not in roots:
            problems.append(f"rows/{rel}: no root")
            continue
        rows_of(table(rel))  # a malformed snapshot raises
        want = sorted(table(rel), key=lambda r: [p.encode() for p in r["key"]])
        root = roots[rel]
        if not want:
            if root != {"count": 0}:
                problems.append(f"rows/{rel}: an empty relation's root is not exactly a count of 0")
            continue
        if not isinstance(root, dict) or root.get("count") != len(want) or type(root.get("count")) is not int:
            problems.append(f"rows/{rel}: the count is not the snapshot's {len(want)} rows")
            continue
        got = walk.root(f"rows/{rel}", root, frozenset({"file", "sha256", "levels", "count"}))
        if got is not None and got != want:
            problems.append(f"rows/{rel}: the rows are not the role's snapshot")
        if all(len(r["key"]) == 2 for r in want):
            if rel not in inverse:
                problems.append(f"inverse/{rel}: no root for a relation with two columns")
                continue
            back = sorted(want, key=lambda r: [p.encode() for p in r["key"][::-1]])
            got = walk.root(f"inverse/{rel}", inverse[rel])
            if got is not None and got != back:
                problems.append(f"inverse/{rel}: the rows are not the role's snapshot by the key reversed")
    for rel in sorted(set(inverse) - {r for r in snapshots if table(r) and all(len(x["key"]) == 2 for x in table(r))}):
        problems.append(f"inverse/{rel}: a tree for a relation without two columns or rows")
    walk.unreached()
    return problems


def _prefix(bound) -> bool:
    return list(bound) == list(range(len(bound)))


def check_indexes(plan: dict, snapshots: dict, pieces: dict, entries: list, limit: int, fanout: int) -> list[str]:
    """Problems with one role's `gap` indexes; empty when they are exactly what the plan needs.

    `plan` is the compiler's gap plan (rede.gap/1), `snapshots` the role's snapshot bytes per relation,
    `pieces` the index pieces by path and `entries` the view index's list: per pattern {"relation", "bound"}
    with {"file", "sha256", "levels"}, or {"tree": "inverse"} for a relation of two columns with [1] bound
    (that tree is check_rows's). The plan itself is the compiler's, held to Soufflé in its tests; here only
    its `indexes` are checked against its own schedules."""
    problems: list[str] = []
    lookups = {(i["relation"], tuple(i["bound"])) for s in plan.get("starts", []) for r in s["rules"]
               for i in r["items"] if "bound" in i}
    want = sorted((r, list(b)) for r, b in lookups if not _prefix(b))
    have = [(i["relation"], i["bound"]) for i in plan.get("indexes", [])]
    if have != want:
        problems.append(f"gap: the plan's indexes are not the lookups of its schedules that need one ({len(have)} for {len(want)})")
    walk = _Walk(pieces, limit, fanout, problems)
    given = {}
    for e in entries:
        k = (e.get("relation"), tuple(e.get("bound", ())))
        if k in given:
            problems.append(f"gap: {k[0]} {list(k[1])} listed twice")
        given[k] = e
    for rel, bound in want:
        rs = json.loads(snapshots[rel]) if rel in snapshots else []
        k = (rel, tuple(bound))
        if not rs:
            if k in given:
                problems.append(f"gap: an index of {rel} {bound}, a relation the role has no rows of")
            continue
        e = given.get(k)
        if e is None:
            problems.append(f"gap: no index of {rel} {bound}")
            continue
        if bound == [1] and all(len(r["key"]) == 2 for r in rs):
            if e != {"relation": rel, "bound": bound, "tree": "inverse"}:
                problems.append(f"gap: {rel} {bound} is the inverse tree's, not a tree of its own")
            continue
        root = {x: e[x] for x in e if x not in ("relation", "bound")}
        name = "index:" + ",".join(str(i) for i in bound)
        got = walk.root(f"{name}/{rel}", root)
        expect = sorted(rs, key=lambda r: [p.encode() for p in _permuted(r["key"], bound)])
        if got is not None and got != expect:
            problems.append(f"{name}/{rel}: the rows are not the role's snapshot by the bound columns first")
    for k in sorted(set(given) - {(r, tuple(b)) for r, b in want}):
        problems.append(f"gap: an index of {k[0]} {list(k[1])} that the plan does not need")
    walk.unreached()
    return problems


def check_sources(entries: list, pieces: dict, roots: dict, limit: int, fanout: int) -> list[str]:
    """Problems with one role's source trees (S25); empty when they hold exactly the role's source entries.

    `entries` is the role's source-entry file (its own correctness is rede_checker.sources'), `pieces` the
    bytes per path and `roots` {relation: {"file", "sha256", "levels"}}: per relation the role has entries of,
    and only those, one tree whose rows are its entries without the row reference ({"key": the key's text
    parts, "sources"[, "reason"]}), in key order (text by its UTF-8 bytes), each key once."""
    problems: list[str] = []
    want: dict[str, list] = {}
    for e in entries:
        row = e.get("row") if isinstance(e, dict) else None
        key = json.loads(row["key"]) if isinstance(row, dict) and isinstance(row.get("key"), str) else None
        if not isinstance(key, list) or not all(isinstance(p, str) for p in key) or not isinstance(row.get("relation"), str):
            return ["sources: an entry has no row reference with a key of text parts"]
        want.setdefault(row["relation"], []).append({"key": key} | {k: v for k, v in e.items() if k != "row"})
    walk = _Walk(pieces, limit, fanout, problems)
    for rel in sorted(set(roots) | set(want)):
        if rel not in want:
            problems.append(f"sources/{rel}: a tree for a relation the role has no entries of")
            continue
        if rel not in roots:
            problems.append(f"sources/{rel}: no tree")
            continue
        expect = sorted(want[rel], key=lambda r: [p.encode() for p in r["key"]])
        if len({json.dumps(r["key"]) for r in expect}) != len(expect):
            problems.append(f"sources/{rel}: two entries for one row")
            continue
        got = walk.root(f"sources/{rel}", roots[rel])
        if got is not None and got != expect:
            problems.append(f"sources/{rel}: the rows are not the role's source entries")
    walk.unreached()
    return problems
