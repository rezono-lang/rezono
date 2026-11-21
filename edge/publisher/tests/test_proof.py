"""The proof graph of a role as key-range pieces (rezono_publisher.proof).

Each tree the publisher makes is checked by the independent checker (rezono_checker.proof): a neutral,
hand-made graph cut into small pieces so that trees get several levels, and every example pack as published
(that part needs DuckDB). Generic: no pack is named."""

import json
from pathlib import Path

import pytest

from rezono_canon import canonical_json
from rezono_checker.proof import check_indexes, check_proof, check_rows, check_sources
from rezono_compiler import gap, rules_dl
from rezono_compiler import rules as ir
from rezono_compiler.explain import key_text
from rezono_publisher import proof

ROOT = Path(__file__).resolve().parents[3]

PROGRAM = """
.decl path(x: symbol, y: symbol)
path(x, y) :- e(x, y).
.decl deg(x: symbol, n: number)
deg(x, n) :- v(x), n = count : { e(x, _) }.
"""
NODES = [f"n{i:02d}" for i in range(40)]
EDGES = [(a, b) for i, a in enumerate(NODES) for b in NODES[i + 1:i + 4]]


def k(*parts):
    return key_text(parts)


def snapshot(keys):
    return ("[\n" + ",\n".join(json.dumps({"key": list(p)}, separators=(",", ":")) for p in sorted(keys, key=lambda p: k(*p)))
            + "\n]\n").encode()


def graph():
    doc = rules_dl.read_program(PROGRAM, "test.dl", {"v": [("x", "string")], "e": [("x", "string"), ("y", "string")]}, "test")
    degree = {a: sum(1 for x, _ in EDGES if x == a) for a in NODES}
    witnesses = [{"conclusion": {"relation": "path", "key": k(a, b)}, "rule_id": "path",
                  "bindings": [{"variable": "?x", "value": a}, {"variable": "?y", "value": b}],
                  "premises": [{"row": {"relation": "e", "key": k(a, b)}, "polarity": "positive", "stratum": 0}]}
                 for a, b in EDGES]
    witnesses += [{"conclusion": {"relation": "deg", "key": k(a, str(degree[a]))}, "rule_id": "deg",
                   "bindings": [{"variable": "?x", "value": a}, {"variable": "?n", "value": str(degree[a])}],
                   "premises": [{"row": {"relation": "v", "key": k(a)}, "polarity": "positive", "stratum": 0}],
                   "aggregates": [{"relation": "e", "position": 0, "group_key": k(a), "count": degree[a],
                                   "contributors_sha256": "-", "result": f"known:{degree[a]}"}]} for a in NODES]
    snapshots = {"e": snapshot(EDGES), "v": snapshot([(a,) for a in NODES]), "path": snapshot(EDGES),
                 "deg": snapshot([(a, str(degree[a])) for a in NODES])}
    return doc, {"witnesses": witnesses, "hidden": [], "load_bearing_entries": _lb_entries(witnesses)}, snapshots


def _lb_entries(witnesses):
    seen = {}
    for w in witnesses:
        c = w["conclusion"]
        for p in w.get("premises", ()):
            seen[(c["relation"], c["key"], p["row"]["relation"], p["row"]["key"], p["polarity"])] = True
    return [
        {"conclusion": {"relation": cr, "key": ck}, "premise": {"relation": pr, "key": pk},
         "how": how, "load_bearing": flag}
        for (cr, ck, pr, pk, how), flag in sorted(seen.items())
    ]


def calc(relation, subject, value, premises=()):
    """A calculation witness as the trees carry it: unchanged, its premises in order."""
    return {"conclusion": {"relation": relation, "key": k(subject, value, "known", "")}, "rule": relation.removeprefix("c__"),
            "version": "1", "definition": "d", "value": value, "state": "known", "reason": "", "reads": ["e"],
            "premises": list(premises), "steps": [{"path": "d/value", "value": value, "state": "known", "reason": ""}]}


def with_calc(sees, snapshots):
    """A calculation per node over its `deg` row, one over that calculation, and one without premises."""
    deg = {json.loads(w["conclusion"]["key"])[0]: w["conclusion"] for w in sees["witnesses"] if w["rule_id"] == "deg"}
    first = [calc("c__first", a, json.loads(deg[a]["key"])[1], [deg[a]]) for a in NODES]
    second = [calc("c__second", a, w["value"], [w["conclusion"]]) for a, w in zip(NODES, first)]
    alone = [calc("c__alone", a, "0") for a in NODES]
    for rel, ws in (("c__first", first), ("c__second", second), ("c__alone", alone)):
        snapshots[rel] = snapshot([tuple(json.loads(w["conclusion"]["key"])) for w in ws])
    return sees | {"calc_witnesses": first + second + alone}, snapshots


# A calculation's key is longer (subject, value, state, reason): its small pieces are a little larger.
@pytest.mark.parametrize("limit,fanout,calculated", [(proof.PIECE, proof.FANOUT, False), (900, 3, False), (700, 2, False),
                                                     (proof.PIECE, proof.FANOUT, True), (1400, 3, True), (1100, 2, True)])
def test_trees_of_every_size_pass_the_independent_check(limit, fanout, calculated):
    doc, sees, snapshots = graph()
    if calculated:
        sees, snapshots = with_calc(sees, snapshots)
    made, roots = proof.plan(doc, sees, snapshots, "p/m/r/views", limit, fanout)
    pieces = {key.removeprefix("p/m/r/views/"): data for key, data in made}
    assert check_proof(doc, sees, snapshots, pieces, roots, limit, fanout) == []
    assert all(len(data) <= limit for data in pieces.values())
    if limit < proof.PIECE:
        assert max(r["levels"] for by in roots.values() for r in by.values()) >= 3, "small pieces give several levels"
    # Made again: the same bytes.
    assert proof.plan(doc, sees, snapshots, "p/m/r/views", limit, fanout) == (made, roots)


def test_calculation_witnesses_are_in_the_trees_with_an_edge_per_premise():
    """A calculation is a conclusion like a rule's: its witness unchanged in the witness tree, each premise a
    positive step at its index; one without premises is in the witness tree only. Also without rules."""
    doc, sees, snapshots = graph()
    sees, snapshots = with_calc(sees, snapshots)
    made, roots = proof.plan(doc, sees, snapshots, "")
    pieces = {key.lstrip("/"): data for key, data in made}
    leaf = lambda tree, rel: json.loads(pieces[roots[tree][rel]["file"]])["rows"]
    assert leaf("witness", "c__second") == sorted([w for w in sees["calc_witnesses"] if w["conclusion"]["relation"] == "c__second"],
                                                  key=lambda w: w["conclusion"]["key"])
    first = next(w for w in sees["calc_witnesses"] if w["conclusion"]["relation"] == "c__first")
    assert [first["conclusion"]["key"], "positive", 0, "deg", first["premises"][0]["key"]] in leaf("back", "c__first")
    assert "c__alone" in roots["witness"] and "c__alone" not in roots["back"] and "c__alone" not in roots["forward"]
    assert sorted(roots["forward"]) == ["c__first", "deg", "e", "v"]

    only = {"witnesses": [], "hidden": [], "calc_witnesses": [w for w in sees["calc_witnesses"] if w["conclusion"]["relation"] != "c__first"]}
    only["calc_witnesses"] = [w | {"premises": []} if w["conclusion"]["relation"] == "c__second" else w for w in only["calc_witnesses"]]
    made, roots = proof.plan(None, only, snapshots, "")
    pieces = {key.lstrip("/"): data for key, data in made}
    assert check_proof({"rules": []}, only, snapshots, pieces, roots, proof.PIECE, proof.FANOUT) == []
    assert sorted(roots["witness"]) == ["c__alone", "c__second"] and roots["back"] == {}


def test_a_calculation_edge_the_witness_does_not_name_is_found():
    """The checker rebuilds the calculation steps on its own: a premise dropped from a piece, or an edge at
    another index, is found."""
    doc, sees, snapshots = graph()
    sees, snapshots = with_calc(sees, snapshots)
    made, roots = proof.plan(doc, sees, snapshots, "")
    pieces = {key.lstrip("/"): data for key, data in made}
    back = roots["back"]["c__second"]["file"]
    changed = dict(pieces) | {back: pieces[back].replace(b'"positive",0', b'"positive",1', 1)}
    assert check_proof(doc, sees, snapshots, changed, roots, proof.PIECE, proof.FANOUT)
    fewer = sees | {"calc_witnesses": [w for w in sees["calc_witnesses"] if w["conclusion"]["relation"] != "c__first"]}
    assert any("c__first" in p for p in check_proof(doc, fewer, snapshots, pieces, roots, proof.PIECE, proof.FANOUT))


def test_a_changed_piece_is_found_and_a_row_larger_than_a_piece_is_refused():
    doc, sees, snapshots = graph()
    made, roots = proof.plan(doc, sees, snapshots, "", 900, 3)
    pieces = {key.lstrip("/"): data for key, data in made}
    leaf = next(p for p in sorted(pieces) if p.startswith("proof/forward/e/0/"))
    pieces[leaf] = pieces[leaf].replace(b"contributes", b"positive", 1)
    assert check_proof(doc, sees, snapshots, pieces, roots, 900, 3)
    with pytest.raises(proof.TooLarge):
        proof.plan(doc, sees, snapshots, "", 60, 3)


PACKS = sorted(p.parent for p in (ROOT / "examples").rglob("pack.yaml")
               if "expected" not in p.parts and (p.parent / "facts").is_dir())


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.relative_to(ROOT / "examples").as_posix())
def test_the_proof_pieces_of_every_example_pass(pack_dir, tmp_path):
    pytest.importorskip("duckdb")
    from rezono_publisher import batch, publish, store, views

    st = store.FileStore(tmp_path / "store")
    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    try:
        mid = publish.publish(e, st, {"checker": "complete", "viewer": "may_read"})["id"]
    except publish.Blocked:
        pytest.skip("a red pack publishes nothing")
    m = json.loads(st.get(f"{e.pack}/manifests/{mid}.json"))
    mine = [s for s in m["snapshots"] if s["role"] == "viewer"]
    snapshots = {s["relation"]: st.get(views.key_of(s["uri"])) for s in mine}
    made, part = views._proof(st, e.pack, mid, m, "viewer", snapshots)  # checked inside; Blocked otherwise
    _, rows = views._rows(st, e.pack, mid, "viewer", snapshots)  # checked inside too
    assert set(rows["trees"]) == set(snapshots)
    assert all(t["count"] == len(json.loads(snapshots[rel])) for rel, t in rows["trees"].items())
    w = next(x for x in m["witnesses"] if x["role"] == "viewer")
    sees = json.loads(st.get(views.key_of(w["uri"])))
    concluded = {x["conclusion"]["relation"] for x in sees["witnesses"] + sees.get("calc_witnesses", [])}
    assert set(part["trees"]["witness"]) == concluded
    assert part["format"] == "rezono.proof-index/3"
    for by in part["trees"].values():
        for named in by.values():
            assert proof.sha256(st.get(views.key_of(named["uri"])) or dict(made)[views.key_of(named["uri"])]) == named["sha256"]


def test_keys_too_long_for_two_children_a_page_are_refused_not_looped():
    """Each leaf holds one row and each page one child: the levels would never shrink, so it is refused."""
    doc, _, _ = graph()
    long = ["x" * 100 + str(i) for i in range(3)]
    witnesses = [{"conclusion": {"relation": "path", "key": k(a, a)}, "rule_id": "path",
                  "bindings": [{"variable": "?x", "value": a}, {"variable": "?y", "value": a}],
                  "premises": [{"row": {"relation": "e", "key": k(a, a)}, "polarity": "positive", "stratum": 0}]}
                 for a in long]
    snapshots = {"e": snapshot([(a, a) for a in long]), "path": snapshot([(a, a) for a in long])}
    with pytest.raises(proof.TooLarge, match="do not hold two children"):
        proof.plan(doc, {"witnesses": witnesses, "hidden": []}, snapshots, "", 1200, 3)


@pytest.mark.parametrize("limit,fanout", [(proof.PIECE, proof.FANOUT), (600, 3), (400, 2)])
def test_row_trees_of_every_size_pass_the_independent_check(limit, fanout):
    """Each relation's snapshot as a tree; text ordered by its UTF-8 bytes (U+1F600 after U+FFFF, unlike
    UTF-16), a key before every longer key it begins; an empty relation has a count of 0 and no tree."""
    _, _, snapshots = graph()
    snapshots["u"] = snapshot([("\U0001F600",), ("\uffff",), ("a b",), ("a", "b"), ("a",)])
    snapshots["none"] = snapshot([])
    made, roots, inverse = proof.rows_plan(snapshots, "p/m/r/views", limit, fanout)
    pieces = {key.removeprefix("p/m/r/views/"): data for key, data in made}
    assert check_rows(snapshots, pieces, roots, limit, fanout, inverse) == []
    assert set(inverse) == {"e", "path", "deg"}, "relations with two columns, and only those"
    assert check_rows(snapshots, pieces, roots, limit, fanout, {}) != [], "a missing inverse tree is found"
    assert roots["none"] == {"count": 0}
    leaves = [json.loads(pieces[p])["rows"] for p in sorted(pieces) if p.startswith("rows/u/0/")]
    keys = [r["key"] for piece in sorted(leaves, key=lambda rs: [x.encode() for x in rs[0]["key"]]) for r in piece]
    assert keys == [["a"], ["a", "b"], ["a b"], ["\uffff"], ["\U0001F600"]]
    if limit < proof.PIECE:
        assert roots["e"]["levels"] >= 3, "small pieces give several levels"
    assert proof.rows_plan(snapshots, "p/m/r/views", limit, fanout) == (made, roots, inverse)
    pieces[next(p for p in sorted(pieces) if p.startswith("rows/e/0/"))] += b" "
    assert check_rows(snapshots, pieces, roots, limit, fanout, inverse)



def source_entries():
    """A role's source entries (rezono_publisher.sources): one per edge, and texts ordered by their UTF-8 bytes."""
    out = [{"row": {"relation": "e", "key": canonical_json([a, b])},
            "sources": [{"kind": "pack", "name": "facts/e.yaml", "position": str(i)}]} for i, (a, b) in enumerate(EDGES)]
    for key in [["😀"], ["￿"], ["a b"], ["a", "b"], ["a"]]:
        out.append({"row": {"relation": "u", "key": canonical_json(key)}, "sources": [{"kind": "pack", "name": "u"}]})
    out[-1]["reason"] = "declared"
    return out


@pytest.mark.parametrize("limit,fanout", [(proof.PIECE, proof.FANOUT), (400, 2)])
def test_source_trees_of_every_size_pass_the_independent_check(limit, fanout):
    """S25 by row: per relation a tree of the role's entries without their row reference, by key, so the
    sources of one row are one lookup. The checker rebuilds the rows from the entries on its own."""
    entries = source_entries()
    made, roots = proof.sources_plan(entries, "p/m/r/views", limit, fanout)
    pieces = {key.removeprefix("p/m/r/views/"): data for key, data in made}
    assert check_sources(entries, pieces, roots, limit, fanout) == []
    assert set(roots) == {"e", "u"} and proof.sources_plan([], "b") == ([], {})
    leaves = [json.loads(pieces[p])["rows"] for p in sorted(pieces) if p.startswith("sources/u/0/")]
    rows = [r for piece in sorted(leaves, key=lambda rs: [x.encode() for x in rs[0]["key"]]) for r in piece]
    assert [r["key"] for r in rows] == [["a"], ["a", "b"], ["a b"], ["￿"], ["😀"]]
    assert rows[0] == {"key": ["a"], "sources": [{"kind": "pack", "name": "u"}], "reason": "declared"}
    if limit < proof.PIECE:
        assert roots["e"]["levels"] >= 3, "small pieces give several levels"
    assert proof.sources_plan(entries, "p/m/r/views", limit, fanout) == (made, roots)
    # What the trees hold is the entries, all of them, once: each change below is found.
    assert check_sources(entries[1:], pieces, roots, limit, fanout), "a tree with an entry the role does not have"
    assert check_sources(entries + entries[:1], pieces, roots, limit, fanout), "two entries for one row"
    assert check_sources(entries, pieces, {"e": roots["e"]}, limit, fanout), "a relation without its tree"
    assert check_sources([x for x in entries if x["row"]["relation"] == "e"], pieces, roots, limit, fanout), "a tree for nothing"
    changed = [x | {"sources": [{"kind": "pack", "name": "other"}]} if x["row"]["relation"] == "u" else x for x in entries]
    assert check_sources(changed, pieces, roots, limit, fanout), "other sources"
    pieces[next(p for p in sorted(pieces) if p.startswith("sources/e/0/"))] += b" "
    assert check_sources(entries, pieces, roots, limit, fanout), "a changed piece"

GAP_PROGRAM = """
.decl hop(y: symbol)
hop(y) :- v(y), e(x, y).
.decl tri(z: symbol)
tri(z) :- v(z), t(x, z, w).
"""


@pytest.mark.parametrize("limit,fanout", [(proof.PIECE, proof.FANOUT), (500, 2)])
def test_the_indexes_of_gap_pass_the_independent_check(limit, fanout):
    """A premise test with a bound column that is not a key prefix reads an index: its own tree, or the
    inverse tree for the second of two columns. Only for relations the role has rows of."""
    doc = rules_dl.read_program(GAP_PROGRAM, "gap.dl", {"v": [("x", "string")], "e": [("x", "string"), ("y", "string")],
                                                        "t": [("a", "string"), ("b", "string"), ("c", "string")]}, "gap")
    plan = gap.plan(ir.load(doc))
    assert plan["indexes"] == [{"relation": "e", "bound": [1]}, {"relation": "t", "bound": [1]}]
    snapshots = {"v": snapshot([(a,) for a in NODES]), "e": snapshot(EDGES),
                 "t": snapshot([(a, b, c) for a, b in EDGES for c in ("p", "q")])}
    made, entries = proof.index_plan(plan, snapshots, "p/m/r/views", limit, fanout)
    pieces = {key.removeprefix("p/m/r/views/"): data for key, data in made}
    assert check_indexes(plan, snapshots, pieces, entries, limit, fanout) == []
    assert [e["relation"] for e in entries] == ["e", "t"] and entries[0] == {"relation": "e", "bound": [1], "tree": "inverse"}
    leaves = sorted((json.loads(pieces[p])["rows"] for p in pieces if p.startswith("index/t/1/0/")), key=lambda rs: rs[0]["key"][1])
    keys = [r["key"] for piece in leaves for r in piece]
    assert [x[1] for x in keys] == sorted(x[1] for x in keys), "ordered by the bound column first"
    assert proof.index_plan(plan, snapshots, "p/m/r/views", limit, fanout) == (made, entries)
    # what the check finds: a changed piece, a missing index, one the plan does not need, a plan that lies
    broken = dict(pieces)
    leaf = next(p for p in sorted(broken) if p.startswith("index/t/1/0/"))
    broken[leaf] = broken[leaf].replace(b'"p"', b'"x"', 1)
    assert check_indexes(plan, snapshots, broken, entries, limit, fanout)
    assert check_indexes(plan, snapshots, pieces, entries[:1], limit, fanout)
    assert check_indexes(plan, snapshots, pieces, entries + [{"relation": "v", "bound": [0], "tree": "inverse"}], limit, fanout)
    assert check_indexes({**plan, "indexes": plan["indexes"][1:]}, snapshots, pieces, entries, limit, fanout)
    # a relation the role has no rows of has no index
    empty = {**snapshots, "t": snapshot([])}
    made, entries = proof.index_plan(plan, empty, "", limit, fanout)
    assert [e["relation"] for e in entries] == ["e"]
    assert check_indexes(plan, empty, {k.lstrip("/"): b for k, b in made}, entries, limit, fanout) == []


WEIGHED = """
.decl load(x: symbol, n: number)
load(x, n) :- v(x), n = sum z : { w(x, _, z) }.
.decl deg(x: symbol, n: number)
deg(x, n) :- v(x), n = count : { w(x, _, _) }.
"""


def test_a_contributes_row_of_a_sum_carries_its_value_and_a_changed_one_is_refused():
    """The row of a sum's contributor ends in what it contributes, in both trees; a count's row and a
    premise's do not. The independent check reads the value from the snapshot itself: one changed is refused."""
    doc = rules_dl.read_program(WEIGHED, "test.dl", {"v": [("x", "string")],
                                                     "w": [("x", "string"), ("y", "string"), ("w", "integer")]}, "test")
    aggregate = {"relation": "w", "position": 0, "group_key": k("a"), "count": 2, "contributors_sha256": "-", "result": "-"}
    ws = [{"conclusion": {"relation": name, "key": k("a", n)}, "rule_id": name,
           "bindings": [{"variable": "?x", "value": "a"}, {"variable": "?n", "value": n}],
           "premises": [{"row": {"relation": "v", "key": k("a")}, "polarity": "positive", "stratum": 0}],
           "aggregates": [aggregate]} for name, n in (("deg", "2"), ("load", "-1"))]
    sees = {"witnesses": ws, "hidden": [], "load_bearing_entries": _lb_entries(ws)}
    snapshots = {"v": snapshot([("a",)]), "w": snapshot([("a", "p", "3"), ("a", "q", "-4"), ("b", "p", "5")]),
                 "load": snapshot([("a", "-1")]), "deg": snapshot([("a", "2")])}
    made, roots = proof.plan(doc, sees, snapshots, "")
    pieces = {key.lstrip("/"): data for key, data in made}
    leaf = lambda tree, rel: json.loads(pieces[roots[tree][rel]["file"]])["rows"]
    p, q = k("a", "p", "3"), k("a", "q", "-4")
    assert leaf("back", "load") == [[k("a", "-1"), "contributes", 0, "w", p, "known:3"],
                                    [k("a", "-1"), "contributes", 0, "w", q, "known:-4"],
                                    [k("a", "-1"), "positive", 0, "v", k("a")]]
    assert leaf("back", "deg") == [[k("a", "2"), "contributes", 0, "w", p], [k("a", "2"), "contributes", 0, "w", q],
                                   [k("a", "2"), "positive", 0, "v", k("a")]]
    assert leaf("forward", "w") == [[p, "deg", k("a", "2"), "contributes", 0], [p, "load", k("a", "-1"), "contributes", 0, "known:3"],
                                    [q, "deg", k("a", "2"), "contributes", 0], [q, "load", k("a", "-1"), "contributes", 0, "known:-4"]]
    assert check_proof(doc, sees, snapshots, pieces, roots, proof.PIECE, proof.FANOUT) == []
    assert proof.plan(doc, sees, snapshots, "") == (made, roots)
    # The planted fault: 3 became 2 in the published piece, and the root names the changed piece.
    path = roots["back"]["load"]["file"]
    piece = json.loads(pieces[path])
    piece["rows"][0][-1] = "known:2"
    pieces[path] = proof.dumps(piece)
    roots["back"]["load"]["sha256"] = proof.sha256(pieces[path])
    assert check_proof(doc, sees, snapshots, pieces, roots, proof.PIECE, proof.FANOUT) == [
        "back/load: the rows are not the role's proof graph"]


def test_a_snapshot_cell_that_is_missing_or_not_known_is_none_for_the_engine_rows():
    """A relation with a value column (none in a compiled pack today): a known cell is its text, a record
    without the column or with another state gives None, which `trace.steps` refuses to state as a value."""
    prog = ir.load({"format": "rezono.rules/1", "rules": [], "relations": [
        {"name": "m", "role": "base", "key": [{"name": "x", "type": "string"}], "values": [{"name": "amount", "type": "integer"}]}]})
    records = [{"key": ["a"], "values": {"amount": {"state": "known", "value": "7"}}},
               {"key": ["b"], "values": {"amount": {"state": "unknown"}}}, {"key": ["c"]}]
    assert proof.engine_rows(prog, "m", json.dumps(records).encode()) == [("a", "7"), ("b", None), ("c", None)]
    assert proof.engine_rows(prog, "other", json.dumps([{"key": ["a", "b"]}]).encode()) == [("a", "b")]
