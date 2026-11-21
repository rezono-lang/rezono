"""Check the proof pieces of one role against the role's witnesses and snapshots.

The publisher writes the role's proof graph as key-range trees (rezono_publisher.proof). This module trusts
none of it: it rebuilds the relation `step` on its own, from the rule definitions (premise positions in
rule-body order, polarities from the rule), the calculation witnesses (each premise, positive, at its index)
and the role's snapshots (an aggregate's group: every row that
matches the fixed positions of the aggregate atom under the witness's bindings), and requires every tree to
hold exactly those rows, in order, in pieces within the limits, each named by the sha256 of its bytes, with
no piece left over.

A `contributes` edge of a `sum`, `min` or `max` carries what its row gives the aggregate: the cell
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
from operator import itemgetter
import re

from rezono_canon import canonical_sha256

from .canon import encode_key, strict_json_loads, value_text
from .closure import functional_instances
from .evaluate import cells
from .refusals import Refusal, RefusalError
from .rules import load_rules
from .snapshots import read_rows, rows_of

FORMAT = "rezono.proof/1"
TREES = ("witness", "back", "forward")
# A piece carries exactly its contract, nothing else: no extra field can hide data in a checked piece.
LEAF = {"format", "tree", "relation", "level", "rows"}
PAGE = {"format", "tree", "relation", "level", "children"}
CHILD = {"first", "last", "file", "sha256"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# The checker's own bounds (decisions/central-read-access.md): a caller may pass stricter ones, never looser.
MAX_PIECE = 64 * 1024  # bytes per piece, at most
MAX_FANOUT = 128  # children per page, at most
MAX_LEVELS = 8  # levels per tree, at most


def steps(rules_doc: dict, witnesses: list[dict], rows: dict) -> set[tuple]:
    """The step rows of the witnesses: (c_relation, c_key, p_relation, p_key, how, position), and on a
    `contributes` row of a `sum`, `min` or `max` a seventh element, the value text of the row's cell."""
    rules = load_rules(rules_doc)
    functionals = getattr(rules, "functionals", {})
    groups: dict = {}
    ordered: dict = {}
    func_cache: dict = {}

    def table(relation):
        if relation not in ordered:
            ordered[relation] = sorted(rows.get(relation, {}).values(), key=itemgetter(0))
        return ordered[relation]

    def candidates(rule, func):
        if rule.id not in func_cache:
            by_key: dict[tuple, list[dict[str, str]]] = {}
            by_key_state: dict[tuple, list[tuple[dict[str, str], str]]] = {}
            variables, found = functional_instances(rule, table)
            for row, row_state in found:
                inst_theta = {v: x for v, x in zip(variables, row) if x is not None}
                key_terms = rule.head.terms[:func.key_arity]
                if any(t.startswith("?") and t not in inst_theta for t in key_terms):
                    continue
                dom_key = tuple(inst_theta[t] if t.startswith("?") else t for t in key_terms)
                if row_state == "known":
                    by_key.setdefault(dom_key, []).append(inst_theta)
                else:
                    by_key_state.setdefault(dom_key, []).append((inst_theta, row_state))
            func_cache[rule.id] = (by_key, by_key_state)
        return func_cache[rule.id]

    out = set()
    for w in witnesses:
        rule = rules.get(w["rule_id"])
        if rule is None:
            raise RefusalError(Refusal("unknown_rule", rule=w["rule_id"]))
        theta = {b["variable"]: b["value"] for b in w.get("bindings", [])}

        def subst(atom, env=theta):
            out_terms = []
            for t in atom.terms:
                if t.startswith("?"):
                    if t not in env:
                        raise RefusalError(Refusal("proof_unbound_variable", variable=t, rule=rule.id))
                    out_terms.append(env[t])
                else:
                    out_terms.append(t)
            return tuple(out_terms)

        c = (w["conclusion"]["relation"], w["conclusion"]["key"])
        func = functionals.get(rule.head.relation)
        if func is not None:
            c_parts = strict_json_loads(w["conclusion"]["key"])
            if (w["conclusion"]["relation"] != rule.head.relation or not isinstance(c_parts, list)
                    or len(c_parts) != func.key_arity + 3 or not all(isinstance(p, str) for p in c_parts)):
                raise RefusalError(Refusal("proof_functional_key_malformed", rule=rule.id))
            state, val = c_parts[func.key_arity], c_parts[func.key_arity + 2]
            dom_key = tuple(
                theta[t] if t.startswith("?") else t for t in rule.head.terms[:func.key_arity]
            ) if all(t in theta for t in rule.head.terms[:func.key_arity] if t.startswith("?")) else None
            if dom_key is None:
                raise RefusalError(Refusal("proof_unbound_domain_variable", rule=rule.id))
            dom_key_enc = encode_key(dom_key)
            for i, b in enumerate(rule.body):
                if b.polarity == "positive" and b.atom.relation == func.domain:
                    b_vars = {t for t in b.atom.terms if t.startswith("?")}
                    if b_vars <= set(theta) and subst(b.atom) == dom_key:
                        out.add((*c, b.atom.relation, dom_key_enc, b.polarity, i))
            val_term = rule.head.terms[func.key_arity]
            known_by_key, state_by_key = candidates(rule, func)
            if state == "invalid":
                step_rules = [
                    (r_item, [
                        *candidates(r_item, func)[0].get(dom_key, ()),
                        *(t for t, st in candidates(r_item, func)[1].get(dom_key, ()) if st == "invalid"),
                    ])
                    for r_item in sorted(rules.values(), key=lambda x: x.id)
                    if r_item.head.relation == func.name
                ]
                agg_insts = [
                    *known_by_key.get(dom_key, ()),
                    *(t for t, st in state_by_key.get(dom_key, ()) if st == "invalid"),
                ]
            elif state == "known":
                matching = [
                    inst_theta for inst_theta in known_by_key.get(dom_key, ())
                    if (inst_theta[val_term] if val_term.startswith("?") else val_term) == val
                ]
                step_rules = [(rule, matching)]
                agg_insts = matching
            else:
                state_matching = [t for t, st in state_by_key.get(dom_key, ()) if st == state]
                step_rules = [(rule, state_matching)]
                agg_insts = state_matching
            for r_item, r_insts in step_rules:
                for inst_theta in r_insts:
                    for i, b in enumerate(r_item.body):
                        if {t for t in b.atom.terms if t.startswith("?")} <= set(inst_theta):
                            out.add((*c, b.atom.relation, encode_key(subst(b.atom, inst_theta)), b.polarity, i))
        else:
            for i, b in enumerate(rule.body):
                out.add((*c, b.atom.relation, encode_key(subst(b.atom)), b.polarity, i))
        for i, spec in enumerate(rule.aggregates):
            if func is None:
                envs = [theta]
            elif agg_insts:
                envs = [inst for inst in agg_insts if all(inst.get(k) == v for k, v in theta.items())]
            elif {t for t in spec.atom.terms if t.startswith("?")} <= set(theta):
                envs = [theta]
            else:
                envs = ()
            for env in envs:
                fixed = [(pos, v) for pos, (t, v) in enumerate(zip(spec.atom.terms, subst(spec.atom, env))) if t != "_"]
                at = (spec.atom.relation, len(spec.atom.terms), tuple(pos for pos, _ in fixed))
                if at not in groups:
                    index: dict = {}
                    for k, (parts, values) in rows.get(spec.atom.relation, {}).items():
                        if len(parts) == at[1]:
                            index.setdefault(tuple(parts[pos] for pos in at[2]), []).append((k, parts, values))
                    groups[at] = index
                members = groups[at].get(tuple(v for _, v in fixed), ())
                given = ([()] * len(members)
                         if spec.function == "count" and (spec.format == "rezono.rules/1"
                                                          or (spec.over is None and getattr(spec, "state_key", None) is None))
                         else [(value_text(v),) for v in cells(spec, [(parts, values) for _, parts, values in members])])
                out |= {(*c, spec.atom.relation, k, "contributes", i, *v) for (k, _, _), v in zip(members, given)}
    return out


def calc_steps(calc_witnesses: list[dict]) -> set[tuple]:
    """The step rows of calculation witnesses: each premise, `positive`, at its index in `premises`.
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
        self.pieces, self.problems = pieces, problems
        self.reached: set = set()
        if type(limit) is not int or not 1 <= limit <= MAX_PIECE:
            problems.append(Refusal("proof_piece_limit_invalid", limit=repr(limit), bound=MAX_PIECE))
            self.limit = MAX_PIECE
        else:
            self.limit = limit
        if type(fanout) is not int or not 2 <= fanout <= MAX_FANOUT:
            problems.append(Refusal("proof_fanout_invalid", limit=repr(fanout), bound=MAX_FANOUT))
            self.fanout = MAX_FANOUT
        else:
            self.fanout = fanout

    def read(self, path, digest, tree, relation, level):
        problems = self.problems
        if path not in self.pieces:
            problems.append(Refusal("piece_missing", path=path))
            return None
        data = self.pieces[path]
        self.reached.add(path)
        if hashlib.sha256(data).hexdigest() != digest:
            problems.append(Refusal("piece_hash_mismatch", path=path))
            return None
        if len(data) > self.limit:
            problems.append(Refusal("piece_too_large", path=path, size=len(data), limit=self.limit))
            return None
        try:
            piece = strict_json_loads(data)
        except ValueError as err:
            text = str(err)
            if text == "duplicate JSON object key":
                problems.append(Refusal("piece_duplicate_json_key", path=path))
            elif text.startswith("non-standard JSON constant "):
                problems.append(Refusal("piece_nonstandard_json_constant", path=path,
                                        value=text.removeprefix("non-standard JSON constant ")))
            else:
                problems.append(Refusal("piece_invalid_json", path=path))
            return None
        if not isinstance(piece, dict) or set(piece) != (LEAF if level == 0 else PAGE):
            actual = sorted(piece) if isinstance(piece, dict) else type(piece).__name__
            if level == 0:
                problems.append(Refusal("piece_leaf_fields_invalid", path=path, fields=actual))
            else:
                problems.append(Refusal("piece_page_fields_invalid", path=path, fields=actual))
            return None
        head = {k: piece[k] for k in ("format", "tree", "relation", "level")}
        if head != {"format": FORMAT, "tree": tree, "relation": relation, "level": level} or type(piece["level"]) is not int:
            problems.append(Refusal("piece_header_mismatch", path=path, value=head, level=level, tree=tree, relation=relation))
            return None
        if level == 0:
            rows = piece["rows"]
            if not isinstance(rows, list) or not rows:
                problems.append(Refusal("piece_rows_invalid", path=path))
                return None
            return rows
        children = piece["children"]
        if not isinstance(children, list) or not children or len(children) > self.fanout:
            problems.append(Refusal("piece_children_invalid", path=path, limit=self.fanout))
            return None
        if not all(isinstance(ch, dict) and set(ch) == CHILD and isinstance(ch["file"], str)
                   and isinstance(ch["sha256"], str) and SHA256.match(ch["sha256"])
                   and isinstance(ch["first"], list) and isinstance(ch["last"], list) for ch in children):
            problems.append(Refusal("piece_child_shape_invalid", path=path, fields=sorted(CHILD)))
            return None
        out = []
        for ch in children:
            got = self.read(ch["file"], ch["sha256"], tree, relation, level - 1)
            if got is None:
                continue
            if not got or [sort_key(tree, got[0]), sort_key(tree, got[-1])] != [ch["first"], ch["last"]]:
                problems.append(Refusal("piece_bounds_mismatch", path=ch["file"]))
            out += got
        return out

    def root(self, name, root, keys=frozenset({"file", "sha256", "levels"})):
        """The rows of one tree down from its root, or None (a problem) if the root is not well-formed."""
        if not isinstance(root, dict) or set(root) != keys or type(root["levels"]) is not int or root["levels"] < 1:
            self.problems.append(Refusal("tree_root_invalid", tree=name, fields=sorted(keys)))
            return None
        if root["levels"] > MAX_LEVELS:
            self.problems.append(Refusal("tree_levels_exceeded", tree=name, level=root["levels"], limit=MAX_LEVELS))
            return None
        tree, relation = name.split("/", 1)
        return self.read(root["file"], root["sha256"], tree, relation, root["levels"] - 1)

    def unreached(self):
        for path in sorted(set(self.pieces) - self.reached):
            self.problems.append(Refusal("piece_unreached", path=path))


def load_bearing(rules_doc: dict, witnesses: list[dict], rows: dict) -> dict[tuple[str, str, str, str, str], bool]:
    """Recompute per-premise load_bearing from a role's founded witnesses and snapshots (decisions/publish-founded-witnesses.md).

    A premise (p_rel, p_key, how) with how in ('positive', 'negative') is load_bearing for conclusion
    (c_rel, c_key) iff it appears in every founded witness of that conclusion.
    """
    rules = load_rules(rules_doc)
    functionals = getattr(rules, "functionals", {})
    by_conclusion: dict[tuple[str, str], list[set[tuple[str, str, str]]]] = {}
    for w in witnesses:
        c = (w["conclusion"]["relation"], w["conclusion"]["key"])
        rule = rules.get(w["rule_id"])
        if rule is None:
            raise RefusalError(Refusal("unknown_rule", rule=w["rule_id"]))
        if rule.head.relation in functionals:
            w_steps = steps(rules_doc, [w], rows)
            prems = {
                (p_rel, p_key, how)
                for c_rel, c_key, p_rel, p_key, how, *_ in w_steps
                if (c_rel, c_key) == c and how in ("positive", "negative")
            }
        else:
            theta = {b["variable"]: b["value"] for b in w.get("bindings", [])}
            prems = set()
            for b in rule.body:
                terms = []
                for t in b.atom.terms:
                    if t.startswith("?"):
                        if t not in theta:
                            raise RefusalError(Refusal("proof_unbound_variable", variable=t, rule=rule.id))
                        terms.append(theta[t])
                    else:
                        terms.append(t)
                if b.polarity in ("positive", "negative"):
                    prems.add((b.atom.relation, encode_key(tuple(terms)), b.polarity))
        by_conclusion.setdefault(c, []).append(prems)
    out: dict[tuple[str, str, str, str, str], bool] = {}
    for (c_rel, c_key), prem_sets in by_conclusion.items():
        all_prems = set().union(*prem_sets) if prem_sets else set()
        for p_rel, p_key, how in sorted(all_prems):
            out[(c_rel, c_key, p_rel, p_key, how)] = all((p_rel, p_key, how) in s for s in prem_sets)
    return out


def _with_iri(w: dict, base_iri: str | None) -> dict:
    if not base_iri:
        return w
    raw = {k: v for k, v in w.items() if k != "iri"}
    return {**raw, "iri": f"{base_iri}witness/{canonical_sha256(raw)}"}


def check_proof(rules_doc: dict, sees: dict, snapshots: dict, pieces: dict, roots: dict, limit: int, fanout: int,
                *, base_iri: str | None = None, require_load_bearing: bool = True) -> list[str]:
    """Problems with one role's proof pieces; empty when they are exactly the role's proof graph.

    `sees` is the role's witness file, `snapshots` its snapshot bytes per relation, `pieces` the bytes per
    path and `roots` {tree: {relation: {"file", "sha256", "levels"}}}."""
    problems: list[str] = []
    rows = {rel: read_rows(b, "json") for rel, b in snapshots.items()}
    calc = sees.get("calc_witnesses", [])
    try:
        stamped = [_with_iri(w, base_iri) for w in sees["witnesses"]]
        want = expected(stamped + calc, steps(rules_doc, sees["witnesses"], rows) | calc_steps(calc))
    except RefusalError as err:
        return [err.refusal]
    except ValueError:
        return [Refusal("proof_steps_invalid")]
    if "load_bearing_entries" in sees or (require_load_bearing and sees["witnesses"]):
        if "load_bearing_entries" not in sees:
            problems.append(Refusal("load_bearing_mismatch"))
        else:
            expected_lb = load_bearing(rules_doc, sees["witnesses"], rows)
            expected_entries = [
                {
                    "conclusion": {"relation": c_rel, "key": c_key},
                    "premise": {"relation": p_rel, "key": p_key},
                    "how": how,
                    "load_bearing": bool(flag),
                }
                for (c_rel, c_key, p_rel, p_key, how), flag in sorted(expected_lb.items())
            ]
            if sees["load_bearing_entries"] != expected_entries:
                problems.append(Refusal("load_bearing_mismatch"))
    walk = _Walk(pieces, limit, fanout, problems)
    for t in TREES:
        given = roots.get(t, {})
        for rel in sorted(set(given) | set(want[t])):
            if rel not in given:
                problems.append(Refusal("proof_tree_missing", tree=t, relation=rel))
                continue
            if rel not in want[t]:
                problems.append(Refusal("proof_tree_unexpected", tree=t, relation=rel))
                continue
            got = walk.root(f"{t}/{rel}", given[rel])
            if got is not None and got != want[t][rel]:
                problems.append(Refusal("proof_rows_mismatch", tree=t, relation=rel))
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

    def table(rel):  # each snapshot is parsed once
        if rel not in parsed:
            parsed[rel] = strict_json_loads(snapshots[rel])
        return parsed[rel]

    for rel in sorted(set(roots) | set(snapshots)):
        if rel not in snapshots:
            problems.append(Refusal("rows_tree_unexpected", relation=rel))
            continue
        if rel not in roots:
            problems.append(Refusal("rows_root_missing", relation=rel))
            continue
        rows_of(table(rel))  # a malformed snapshot raises
        want = sorted(table(rel), key=lambda r: [p.encode() for p in r["key"]])
        root = roots[rel]
        if not want:
            if root != {"count": 0}:
                problems.append(Refusal("rows_empty_root_invalid", relation=rel))
            continue
        if not isinstance(root, dict) or root.get("count") != len(want) or type(root.get("count")) is not int:
            problems.append(Refusal("rows_count_mismatch", relation=rel, count=len(want)))
            continue
        got = walk.root(f"rows/{rel}", root, frozenset({"file", "sha256", "levels", "count"}))
        if got is not None and got != want:
            problems.append(Refusal("rows_snapshot_mismatch", relation=rel))
        if all(len(r["key"]) == 2 for r in want):
            if rel not in inverse:
                problems.append(Refusal("inverse_root_missing", relation=rel))
                continue
            back = sorted(want, key=lambda r: [p.encode() for p in r["key"][::-1]])
            got = walk.root(f"inverse/{rel}", inverse[rel])
            if got is not None and got != back:
                problems.append(Refusal("inverse_rows_mismatch", relation=rel))
    for rel in sorted(set(inverse) - {r for r in snapshots if table(r) and all(len(x["key"]) == 2 for x in table(r))}):
        problems.append(Refusal("inverse_tree_unexpected", relation=rel))
    walk.unreached()
    return problems


def _prefix(bound) -> bool:
    return list(bound) == list(range(len(bound)))


def check_indexes(plan: dict, snapshots: dict, pieces: dict, entries: list, limit: int, fanout: int) -> list[str]:
    """Problems with one role's `gap` indexes; empty when they are exactly what the plan needs.

    `plan` is the compiler's gap plan (rezono.gap/1), `snapshots` the role's snapshot bytes per relation,
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
        problems.append(Refusal("gap_plan_indexes_mismatch", count=len(have), size=len(want)))
    walk = _Walk(pieces, limit, fanout, problems)
    given = {}
    for e in entries:
        k = (e.get("relation"), tuple(e.get("bound", ())))
        if k in given:
            problems.append(Refusal("gap_index_duplicate", relation=k[0], bound=list(k[1])))
        given[k] = e
    for rel, bound in want:
        rs = strict_json_loads(snapshots[rel]) if rel in snapshots else []
        k = (rel, tuple(bound))
        if not rs:
            if k in given:
                problems.append(Refusal("gap_index_empty_relation", relation=rel, bound=bound))
            continue
        e = given.get(k)
        if e is None:
            problems.append(Refusal("gap_index_missing", relation=rel, bound=bound))
            continue
        if bound == [1] and all(len(r["key"]) == 2 for r in rs):
            if e != {"relation": rel, "bound": bound, "tree": "inverse"}:
                problems.append(Refusal("gap_index_not_inverse", relation=rel, bound=bound))
            continue
        root = {x: e[x] for x in e if x not in ("relation", "bound")}
        name = "index:" + ",".join(str(i) for i in bound)
        got = walk.root(f"{name}/{rel}", root)
        expect = sorted(rs, key=lambda r: [p.encode() for p in _permuted(r["key"], bound)])
        if got is not None and got != expect:
            problems.append(Refusal("gap_index_rows_mismatch", tree=name, relation=rel))
    for k in sorted(set(given) - {(r, tuple(b)) for r, b in want}):
        problems.append(Refusal("gap_index_unexpected", relation=k[0], bound=list(k[1])))
    walk.unreached()
    return problems


def check_sources(entries: list, pieces: dict, roots: dict, limit: int, fanout: int) -> list[str]:
    """Problems with one role's source trees; empty when they hold exactly the role's source entries.

    `entries` is the role's source-entry file (its own correctness is rezono_checker.sources'), `pieces` the
    bytes per path and `roots` {relation: {"file", "sha256", "levels"}}: per relation the role has entries of,
    and only those, one tree whose rows are its entries without the row reference ({"key": the key's text
    parts, "sources"[, "reason"]}), in key order (text by its UTF-8 bytes), each key once."""
    problems: list[str] = []
    want: dict[str, list] = {}
    for e in entries:
        row = e.get("row") if isinstance(e, dict) else None
        try:
            key = strict_json_loads(row["key"]) if isinstance(row, dict) and isinstance(row.get("key"), str) else None
        except ValueError:
            key = None
        if not isinstance(key, list) or not all(isinstance(p, str) for p in key) or not isinstance(row.get("relation"), str):
            return [Refusal("sources_entry_row_invalid")]
        want.setdefault(row["relation"], []).append({"key": key} | {k: v for k, v in e.items() if k != "row"})
    walk = _Walk(pieces, limit, fanout, problems)
    for rel in sorted(set(roots) | set(want)):
        if rel not in want:
            problems.append(Refusal("sources_tree_unexpected", relation=rel))
            continue
        if rel not in roots:
            problems.append(Refusal("sources_tree_missing", relation=rel))
            continue
        expect = sorted(want[rel], key=lambda r: [p.encode() for p in r["key"]])
        if len({json.dumps(r["key"]) for r in expect}) != len(expect):
            problems.append(Refusal("sources_duplicate_row", relation=rel))
            continue
        got = walk.root(f"sources/{rel}", roots[rel])
        if got is not None and got != expect:
            problems.append(Refusal("sources_rows_mismatch", relation=rel))
    walk.unreached()
    return problems
