"""The difference of a proposal or variant against its base (R10 step 7): the publisher's entries against
the checker's own comparison, the checker's refusals, and the step on a published proposal."""

import json
import random
import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml

from rezono_checker.difference import changes, check_difference
from rezono_publisher import proof
from rezono_publisher.difference import entries

LIMIT, FANOUT = 700, 3  # small, so a tree has several levels; a page still holds two children


def snap(rows) -> bytes:
    return json.dumps([{"key": list(r)} for r in sorted(rows)]).encode()


def made(before, after, rel="r"):
    """(pieces, counts, roots) as the publisher writes them for one relation."""
    rs = entries(snap(before), snap(after))
    if not rs:
        return {}, {}, {}
    root, levels, files = proof.tree("difference", rel, rs, lambda lv, n: f"difference/{rel}/{lv}/{n}.json", LIMIT, FANOUT)
    c = Counter(e["change"] for e in rs)
    return (files, {rel: {k: c[k] for k in ("added", "removed", "changed")}},
            {rel: {"file": root, "sha256": proof.sha256(files[root]), "levels": levels}})


UNIVERSE = ([(a,) for a in "abcé"] + [(a, b) for a in "ab" for b in "xyz"] + [("", b) for b in "xy"]
            + [(a, b, c) for a in "ab" for b in "xy" for c in "12"])


def test_the_publisher_and_the_checker_agree_on_random_snapshots():
    rnd = random.Random(7)
    for _ in range(300):
        before = {u for u in UNIVERSE if rnd.random() < 0.5}
        after = {u for u in UNIVERSE if rnd.random() < 0.5}
        assert entries(snap(before), snap(after)) == changes(snap(before), snap(after))
        pieces, counts, roots = made(before, after)
        assert check_difference({"r": snap(before)}, {"r": snap(after)}, pieces, counts, roots, LIMIT, FANOUT) == []


def test_a_single_valued_cell_is_one_change_and_the_rest_rows():
    before = {("a", "1"), ("b", "1"), ("b", "2"), ("k",)}
    after = {("a", "2"), ("b", "1"), ("b", "3"), ("l",)}
    assert entries(snap(before), snap(after)) == [
        {"key": ["a", "2"], "change": "changed", "was": ["a", "1"]},
        {"key": ["b", "2"], "change": "removed"},
        {"key": ["b", "3"], "change": "added"},
        {"key": ["k"], "change": "removed"},  # a row of one column is never a cell
        {"key": ["l"], "change": "added"},
    ]


def test_no_change_is_no_tree():
    assert entries(snap({("a", "1")}), snap({("a", "1")})) == []
    assert check_difference({"r": snap({("a",)})}, {"r": snap({("a",)})}, {}, {}, {}, LIMIT, FANOUT) == []


def test_a_relation_on_one_side_only_counts_as_empty_on_the_other():
    pieces, counts, roots = made(set(), {("a",), ("b",)})
    assert counts == {"r": {"added": 2, "removed": 0, "changed": 0}}
    assert check_difference({}, {"r": snap({("a",), ("b",)})}, pieces, counts, roots, LIMIT, FANOUT) == []


@pytest.mark.parametrize("spoil", ["count", "entry", "listed", "extra", "missing"])
def test_the_checker_refuses_what_is_not_the_change(spoil):
    before, after = {("a", "1"), ("b",)}, {("a", "2"), ("c",)}
    pieces, counts, roots = made(before, after)
    b, a = {"r": snap(before)}, {"r": snap(after)}
    if spoil == "count":
        counts["r"]["added"] += 1
    elif spoil == "entry":  # a leaf that drops an entry, its hash made to match
        leaf = next(p for p in pieces if "/0/" in p)
        piece = json.loads(pieces[leaf])
        piece["rows"] = piece["rows"][1:]
        pieces = {leaf: proof.dumps(piece)}
        roots = {"r": {"file": leaf, "sha256": proof.sha256(pieces[leaf]), "levels": 1}}
    elif spoil == "listed":  # a relation that did not change, listed anyway
        b["s"] = a["s"] = snap({("x",)})
        counts["s"] = {"added": 0, "removed": 0, "changed": 0}
    elif spoil == "extra":
        pieces = pieces | {"difference/r/9/9.json": b"{}"}
    elif spoil == "missing":
        roots = {}
    assert check_difference(b, a, pieces, counts, roots, LIMIT, FANOUT)


def test_a_proof_tree_is_named_at_the_base_only_when_the_base_has_that_very_tree():
    """The hash decides, and the place is the one the publisher works out itself: the same path under
    the base's views for the same role. Anything else in the base's index keeps the variant's copy."""
    from rezono_publisher.difference import shared

    class Store(dict):
        def uri(self, key):
            return f"s3://rezono/{key}"

    at, there = "p/v-s-00-2/r/explain", "p/m-2/r/views"

    def root(prefix, rel="q", sha="a" * 64, levels=2):
        return {"uri": f"s3://rezono/{prefix}/proof/witness/{rel}/{levels - 1}/0.json", "sha256": sha, "levels": levels}

    layout = {"format": proof.INDEX, "piece": proof.PIECE, "fanout": proof.FANOUT}
    q = [(f"{at}/proof/witness/q/0/0.json", b"leaf"), (f"{at}/proof/witness/q/1/0.json", b"page")]
    made = q + [(f"{at}/proof/witness/qq/0/0.json", b"other")]  # a relation whose name starts with the other's
    part = layout | {"trees": {"witness": {"q": root(at), "qq": root(at, "qq", "b" * 64, 1)}, "back": {}, "forward": {}},
                     "witnesses": "w", "rules": "r"}

    def over(base_proof):
        st = Store() if base_proof is None else Store({f"{there}/index.json": json.dumps({"proof": base_proof}).encode()})
        return shared(st, "p", "m-2", "r", at, made, part)

    theirs = layout | {"trees": {"witness": {"q": root(there)}}}
    pieces, named = over(theirs)
    witness = part["trees"]["witness"] | {"q": root(there)}  # `qq` stays where it was, with its piece
    assert pieces == made[2:] and named == part | {"trees": part["trees"] | {"witness": witness}}
    kept = (made, part)
    assert over(None) == kept and over({}) == kept  # no view index of the base, or one without a proof graph
    assert over(theirs | {"piece": proof.PIECE // 2}) == kept and over(theirs | {"format": "rezono.proof-index/2"}) == kept
    for other in (root(there, sha="c" * 64), root(there, levels=3), root("p/m-1/r/views"), root("p/m-2/other/views"),
                  root(there) | {"uri": f"s3://rezono/{there}/proof/witness/q/../q/1/0.json"}):
        assert over(theirs | {"trees": {"witness": {"q": other}}}) == kept, other


def test_a_delta_that_may_change_a_right_gets_no_difference_decided_without_data():
    """`may_read` is derived from facts. Whether a delta may change it is decided from the rules and the delta
    alone, so it never depends on an element a role does not see."""
    from rezono_publisher.difference import withheld

    def atom(rel, *terms, polarity="positive"):
        return {"relation": rel, "terms": list(terms), "polarity": polarity}

    rules = {"rules": [
        # Every k is readable: inserting k(x0) grants x0 alone.
        {"id": "a", "head": atom("may_read", "?r", "k", "?x"), "body": [atom("role", "?r"), atom("k", "?x")]},
        # A document through its team, through a membership: a membership grants other elements.
        {"id": "b", "head": atom("may_read", "?r", "doc", "?d"), "body": [atom("in_team", "?r", "?t"), atom("doc__team", "?d", "?t")]},
        {"id": "c", "head": atom("in_team", "?r", "?t"), "body": [atom("member__role", "?m", "?r"), atom("member__team", "?m", "?t")]},
    ]}
    bundle = {"kinds": [{"id": "k"}, {"id": "sub", "parent": "k"}, {"id": "doc"}, {"id": "member"}, {"id": "note"}]}

    def held(*changes):
        return withheld(rules, bundle, {"changes": list(changes)})

    assert not held({"op": "insert", "kind": "k", "key": "x0"})  # its own content
    assert not held({"op": "insert", "kind": "sub", "key": "x0"})  # a subkind of k: the same
    assert not held({"op": "set", "kind": "note", "key": "n", "slot": "text"})  # outside the closure
    assert held({"op": "insert", "kind": "member", "key": "m", "values": {"role": "r", "team": "t"}})  # grants docs
    assert held({"op": "set", "kind": "doc", "key": "d", "slot": "team"})  # moves a document
    assert held({"op": "delete", "kind": "k", "key": "x0"})  # only an insert grants itself
    assert held({"op": "unset", "kind": "doc", "key": "d", "slot": "team"})  # a slot in the closure
    # A set or unset keeps the record and its kind, so a kind in the closure is not written; its slots are.
    assert not held({"op": "set", "kind": "sub", "key": "x0", "slot": "title"})
    assert not held({"op": "unset", "kind": "k", "key": "x0", "slot": "title"})
    assert held({"op": "set", "kind": "k", "key": "x0", "slot": "title"}, {"op": "rename", "kind": "note", "key": "n"})  # unknown op
    assert held({"op": "insert", "kind": "k", "key": "x0"}, {"op": "set", "kind": "doc", "key": "d", "slot": "team"})
    assert withheld(rules, bundle, None) and withheld(rules, None, {"changes": []})  # nothing to decide by
    assert not withheld(None, bundle, {"changes": [{"op": "set", "kind": "doc", "key": "d", "slot": "team"}]})  # no rules, no rights


# The two base relations of the rules that are not schema tables, on fixture packs. A right that rests
# on one of them changes with tables no rule body names.
FIXTURES = Path(__file__).resolve().parents[3] / "compiler" / "tests" / "fixtures"
READ = ".decl may_read(role: symbol, kind: symbol, element: symbol)\n"
ON_REFUSAL = READ + 'may_read("viewer", "beta", b) :- beta(b).\nmay_read("viewer", "alpha", a) :- alpha__refused(a, _).\n'
SET_STATE = {"op": "set", "file": "facts/a.yaml", "kind": "beta", "key": "b1", "slot": "state", "value": "high"}


def sealed_pack(d: Path, rules: str) -> Path:
    """The neutral pack with Alpha sealed on `period`, Beta a part of it (docs/compiler.md#parts) and a kind
    Gamma outside the seal, with one covered Alpha and its part as facts."""
    from rezono_compiler import facts, pack

    shutil.copytree(FIXTURES / "minimal", d)
    schema = yaml.safe_load((d / "schema" / "minimal.yaml").read_text())
    schema["classes"]["Alpha"]["attributes"]["period"] = {"range": "date", "required": True}
    schema["classes"]["Alpha"]["annotations"] = {"seal": "period"}
    schema["classes"]["Beta"]["annotations"] = {"sealed_with": "alpha"}
    schema["classes"]["Gamma"] = {"attributes": {"id": {"identifier": True}, "note": {}}}
    schema["classes"]["PeriodClose"] = {"attributes": {
        "id": {"identifier": True}, "closed_until": {"range": "date", "required": True},
        "covers": {"range": "ClosedAlpha", "multivalued": True, "inlined_as_list": True}}}
    schema["classes"]["ClosedAlpha"] = {"attributes": {
        "element": {"range": "Alpha", "required": True}, "sha256": {"required": True}}}
    (d / "schema" / "minimal.yaml").write_text(yaml.safe_dump(schema, sort_keys=False))
    (d / "rules").mkdir()
    (d / "rules" / "access.dl").write_text(rules)
    records = {"alpha": [{"id": "a1", "title": "t", "size": 1, "period": "2026-01-01"}],
               "beta": [{"id": "b1", "alpha": "a1", "state": "low"}], "gamma": [{"id": "g1", "note": "n"}]}
    covered = dict(facts.rows_of(pack.read(d), records)["alpha__row_sha256"])["a1"]
    records["period_close"] = [{"id": "c0", "closed_until": "2026-06-01", "covers": [{"element": "a1", "sha256": covered}]}]
    (d / "facts").mkdir()
    (d / "facts" / "a.yaml").write_text(yaml.safe_dump(records, sort_keys=False))
    return d


def compiled(d: Path):
    from rezono_compiler import emit, pack

    files = emit.compile_pack(pack.read(d))
    return json.loads(files["ir/rules.json"]), json.loads(files["bundle/schema-bundle.json"])


def test_a_right_on_a_seal_withholds_a_change_to_anything_the_seal_reads(tmp_path):
    """`alpha__refused` follows from Alpha, its parts and the closes: an edited part refuses its element."""
    pytest.importorskip("rezono_compiler")
    from rezono_publisher.difference import withheld

    rules, bundle = compiled(sealed_pack(tmp_path / "on", ON_REFUSAL))
    held = lambda r, **change: withheld(r, bundle, {"changes": [change]})  # noqa: E731
    assert held(rules, **SET_STATE)  # a part: its element's row changes, the close refuses it
    assert held(rules, op="insert", kind="beta", key="b2", values={"alpha": "a1"})
    assert held(rules, op="delete", kind="beta", key="b1")
    assert held(rules, op="insert", kind="period_close", key="c1", values={"closed_until": "2027-01-01"})
    assert held(rules, op="set", kind="period_close", key="c0", slot="closed_until", value="2025-01-01")
    assert held(rules, op="set", kind="closed_alpha", key="x", slot="sha256", value="0" * 64)
    assert held(rules, op="set", kind="alpha", key="a1", slot="size", value=2)
    assert not held(rules, op="set", kind="gamma", key="g1", slot="note", value="m")  # outside the seal
    part = next(p for s in rules["seals"] for p in s["parts"])
    for through in ("alpha__accepted", "alpha__row_sha256", part["accepted"]):  # each relation a seal makes
        other = json.loads(json.dumps(rules).replace("alpha__refused", through))
        assert held(other, **SET_STATE), through
    assert withheld(rules | {"seals": [{"kind": "alpha"}]}, bundle, {"changes": []})  # a seal it cannot read
    # A pack with the same seal whose rights do not rest on it: a part is an ordinary kind again.
    plain, bundle = compiled(sealed_pack(tmp_path / "off", READ + 'may_read("viewer", "beta", b) :- beta(b).\n'))
    assert not held(plain, **SET_STATE)
    assert held(plain, op="delete", kind="beta", key="b1")


def test_a_proposal_that_edits_a_part_gets_no_difference(tmp_path):
    """End to end: the viewer reads Beta, and Alpha only once it is refused. Its proposal on a Beta it reads
    refuses a1, so the proposal's snapshots hold a1 for the viewer; no difference may show them."""
    pytest.importorskip("duckdb")
    from rezono_publisher import batch, proposal, publish, store
    from test_proposal import PACK, ROLES, sh

    repo = tmp_path / "repo"
    sealed_pack(repo / PACK, ON_REFUSAL)
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "add", ".", cwd=repo)
    sh("git", "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", "base", cwd=repo)
    st = store.FileStore(tmp_path / "store")
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    n, time = proposal.base_of(repo, base)
    main = publish.publish(batch.epoch(repo / PACK, epoch=n, knowledge_time=time, sources=[("rules", base)]), st, ROLES)
    delta = json.dumps({"format": "rezono.delta/1", "changes": [SET_STATE]})
    mid = proposal.publish_proposal(repo, PACK, "7", base, delta, st, ROLES)
    title = lambda m: json.loads(st.get(publish.role_objects(st, "minimal", m, "viewer")["relations/alpha__title.json"]))  # noqa: E731
    assert title(main["id"]) == [] and [r["key"] for r in title(mid)] == [["a1", "t"]]  # the right did change
    assert st.list(f"minimal/{mid}/viewer/explain/") == []


def test_a_right_cannot_rest_on_a_calculated_value(tmp_path):
    """Refuted for calculations: no compiled pack has `may_read` downstream of a selection, directly or through
    a derived relation, so no delta to a calculation input changes a right. An IR that had it is withheld."""
    pytest.importorskip("rezono_compiler")
    from rezono_compiler import emit, pack
    from rezono_publisher.difference import withheld

    big = '.decl big(item: symbol)\nbig(x) :- calc__total(x, c, "known", ""), c > 10.\n'
    for name, rules in (("direct", READ + 'may_read("viewer", "item", x) :- calc__total(x, c, "known", ""), c > 10.\n'),
                        ("through", big + READ + 'may_read("viewer", "item", x) :- big(x).\n')):
        d = Path(shutil.copytree(FIXTURES / "calc", tmp_path / name))
        (d / "rules" / "access.dl").write_text(rules)
        with pytest.raises(pack.CompileError, match="may_read cannot depend on a calculation selection"):
            pack.read(d)
    d = Path(shutil.copytree(FIXTURES / "calc", tmp_path / "forged"))
    (d / "rules" / "access.dl").write_text(big + READ + 'may_read("viewer", "item", x) :- item(x).\n')
    files = emit.compile_pack(pack.read(d))
    doc, bundle = json.loads(files["ir/rules.json"]), json.loads(files["bundle/schema-bundle.json"])
    entry = {"changes": [{"op": "set", "kind": "entry", "key": "e", "slot": "number", "value": 99}]}  # a calc input
    assert not withheld(doc, bundle, entry)
    read = next(r for r in doc["rules"] if r["head"]["relation"] == "may_read")
    read["body"][0]["relation"] = "big"  # as if it had come past the compiler: may_read(…, x) :- big(x)
    assert withheld(doc, bundle, entry)
