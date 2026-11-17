"""Theory std-identity (#314 §5.2, T5; lane G, G02): its axioms and rules against independent oracles.

Three evaluations must agree as sets: an exact Python reference written from the definitions (union-find over the
same_as claims, not a join), the DuckDB batch backend on the compiled IR, and Soufflé on the same program (when
present, as in CI). The values a class compares come from a domain's own rules (the theory's @extend relations), so
every case runs through a small neutral domain: by kind (`is_a: Referent`), and by a view with other names that
executes through the bounded profile of RV-C27. No domain: the elements are letters.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings, strategies as st

from rezono_compiler import batch, emit, modules, pack
from rezono_compiler import rules as ir
from support import typed
import souffle

THEORY = Path(__file__).resolve().parents[2] / "packs" / "std-identity"
DERIVED = ["chosen", "class_number", "class_text", "disputed", "equivalent", "has_chosen", "has_equivalent",
           "identity_conflict", "representative", "representative_not_recorded", "representative_outside_class",
           "representatives_disagree", "stated_number", "stated_same", "stated_text"]
INVARIANTS = ["identity_conflict", "representative_outside_class", "representatives_disagree"]
OUT = ["equivalent", "representative", "representative_not_recorded", "representatives_disagree",
       "representative_outside_class", "identity_conflict", "class_text", "class_number"]
# The domain's own rules: it states which of its slots a class compares (here a text and a whole number).
VALUES = '''.decl stated_text(referent: symbol, slot: symbol, value: symbol)
stated_text(x, "label", v) :- item__label(x, v).
.decl stated_number(referent: symbol, slot: symbol, value: number)
stated_number(x, "size", n) :- item__size(x, n).
'''


def reference(items, same_as, represented_by, label, size):
    """The definitions of the README. Classes by union-find over the same_as claims (either way); a class names
    its representative by represented_by at any member; a class of one stands for itself; two members that state
    different values for one slot conflict; the stated values are carried to the representative."""
    parent = {x: x for x in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b in same_as:
        parent[find(a)] = find(b)
    classes = {}
    for x in items:
        classes.setdefault(find(x), set()).add(x)
    members = {x: classes[find(x)] for x in items}
    equivalent = {(a, b) for a in items for b in members[a]}
    chosen = {(a, r) for a in items for x, r in represented_by if x in members[a]}
    named = {a: {r for b, r in chosen if b == a} for a in items}
    representative = {(a, r) for a in items for r in named[a] if r in members[a] and len(named[a]) == 1}
    representative |= {(a, a) for a in items if len(members[a]) == 1}
    conflict = set()
    for slot_rows, slot in ((label, "label"), (size, "size")):
        values = {}
        for x, v in slot_rows:
            values.setdefault(x, set()).add(v)
        conflict |= {(a, b, slot) for a in values for b in values if a != b and b in members[a]
                     and any(v != w for v in values[a] for w in values[b])}
    return {
        "equivalent": equivalent,
        "representative": representative,
        "representative_not_recorded": {(a,) for a in items if len(members[a]) > 1 and not named[a]},
        "representatives_disagree": {(r, s) for a in items for r in named[a] for s in named[a] if r != s},
        "representative_outside_class": {(x, r) for x, r in represented_by if r not in members[x]},
        "identity_conflict": conflict,
        "class_text": {(r, "label", v) for a, r in representative for x, v in label if x == a},
        "class_number": {(r, "size", str(n)) for a, r in representative for x, n in size if x == a},
    }


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")


def domain(tmp_path, view=None):
    """A domain that pins the theory. By kind: its kind Item is a Referent (is_a). By view: its own kind Record,
    with its own arrows `alias_of` and `picked`, is mapped onto Referent by a top-level views.yaml."""
    d = tmp_path / "domain"
    for folder in ("schema", "labels", "rules"):
        (d / folder).mkdir(parents=True)
    write(d / "pack.yaml", {"name": "domain", "version": "0.1.0", "default_language": "en",
                            "imports": [{"name": "std-identity", "path": str(THEORY), "sha256": modules.pack_hash(THEORY)}]})
    if view:
        item = {"attributes": {"id": {"identifier": True}, "label": {}, "size": {"range": "integer"},
                               "alias_of": {"range": "Item", "multivalued": True}, "picked": {"range": "Item"}}}
        imports = ["linkml:types"]
    else:
        item = {"is_a": "Referent", "attributes": {"label": {}, "size": {"range": "integer"}}}
        imports = ["linkml:types", "std-identity:identity"]
    write(d / "schema" / "domain.yaml", {"id": "https://rezono.example/domain", "name": "domain",
          "prefixes": {"linkml": "https://w3id.org/linkml/"}, "imports": imports, "default_range": "string",
          "annotations": {"layer": "facts"}, "classes": {"Item": item}})
    write(d / "labels" / "en.yaml", {"item": "item", "item.label": "label", "item.size": "size"}
          | ({"item.alias_of": "alias of", "item.picked": "picked"} if view else {}))
    write(d / "channels.yaml", {"kinds": [{"kind": "item", "shape": "rect"}]})
    (d / "rules" / "values.dl").write_text(VALUES, encoding="utf-8", newline="\n")
    if view:
        write(d / "views.yaml", {"format": "rezono.views/1", "views": [view]})
    return d


VIEW = {"theory": "std-identity",
        "kinds": [{"name": "referent", "union": [{"populated_from": "item"}]}],
        "arrows": [{"name": "same_as", "paths": [{"populated_from": "item", "steps": [{"slot": "alias_of"}]}]},
                   {"name": "represented_by", "paths": [{"populated_from": "item", "steps": [{"slot": "picked"}]}]}]}


@pytest.fixture(scope="module")
def by_kind(tmp_path_factory):
    return ir.load(pack.read(domain(tmp_path_factory.mktemp("kind"))).rules)


@pytest.fixture(scope="module")
def by_view(tmp_path_factory):
    return ir.load(pack.read(domain(tmp_path_factory.mktemp("view"), VIEW)).rules)


def as_text(result):
    return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in result.items()}


def tables(prog, items, same_as, represented_by, label, size):
    """The fact rows under the names the program reads: the theory's tables (by kind) or the domain's (by view)."""
    if "item__alias_of" in prog.relations:
        rows = {"item": [(x,) for x in items], "item__alias_of": same_as, "item__picked": represented_by}
    else:
        rows = {"item": [(x,) for x in items], "referent": [(x,) for x in items], "referent__same_as": same_as,
                "referent__represented_by": represented_by}
    rows |= {"item__label": label, "item__size": size}
    return {n: typed(prog, n, sorted(set(rows.get(n, [])))) for n, r in prog.relations.items() if r.role == "base"}


def evaluate(prog, items, same_as=(), represented_by=(), label=(), size=()):
    """Every engine at hand on these rows, each compared with the reference."""
    args = (sorted(set(items)), sorted(set(same_as)), sorted(set(represented_by)), sorted(set(label)),
            sorted(set(size)))
    data = tables(prog, *args)
    con = batch.connect(prog, data, threads=1)
    try:
        batch.compute(con, prog)
        got = as_text(batch.read(con, prog, OUT))
    finally:
        con.close()
    assert got == reference(*args)
    if shutil.which("souffle"):
        oracle = souffle.run(prog, data)
        assert {n: oracle[n] for n in OUT} == got
    return got


def test_the_theory_is_fact_free_and_compiles_on_its_own():
    theory = pack.read(THEORY)
    assert theory.meta["theory"] is True and not (THEORY / "facts").exists()
    assert set(theory.kinds) == {"referent"}
    files = emit.compile_pack(theory)
    assert '"referent__same_as"' in files["engine/tables.sql"]
    assert emit.compile_pack(pack.read(THEORY)) == files                           # the same input, the same bytes
    prog = ir.load(theory.rules)
    assert sorted(r.name for r in prog.relations.values() if r.role == "derived") == DERIVED
    assert sorted(r.name for r in prog.relations.values() if getattr(r, "invariant", False)) == INVARIANTS
    assert sorted(r.name for r in prog.relations.values() if getattr(r, "extend", False)) == ["stated_number", "stated_text"]
    assert [q["term"] for q in theory.questions] == ["identity_grounds", "identity_reach"]


def test_same_as_closes_reflexive_symmetric_and_transitive(by_kind):
    # One chain a - b - c stated in mixed directions, and d alone.
    got = evaluate(by_kind, "abcd", same_as=[("a", "b"), ("c", "b")])
    abc = {(x, y) for x in "abc" for y in "abc"}
    assert got["equivalent"] == abc | {("d", "d")}
    assert got["representative"] == {("d", "d")}                                   # a class of one stands for itself
    assert got["representative_not_recorded"] == {("a",), ("b",), ("c",)}          # nobody named one for abc


def test_one_named_member_stands_for_its_class(by_kind):
    got = evaluate(by_kind, "abcd", same_as=[("a", "b"), ("b", "c")], represented_by=[("a", "c")])
    assert got["representative"] == {("a", "c"), ("b", "c"), ("c", "c"), ("d", "d")}
    assert got["representative_not_recorded"] == set() and got["representatives_disagree"] == set()


def test_must_fail_two_representatives_for_one_class(by_kind):
    got = evaluate(by_kind, "abc", same_as=[("a", "b")], represented_by=[("a", "a"), ("b", "b")])
    assert got["representatives_disagree"] == {("a", "b"), ("b", "a")}
    assert {r for r in got["representative"] if r[0] in "ab"} == set()             # no representative is guessed


def test_must_fail_a_representative_outside_its_class(by_kind):
    got = evaluate(by_kind, "abc", same_as=[("a", "b")], represented_by=[("a", "c")])
    assert got["representative_outside_class"] == {("a", "c")}
    assert ("a", "c") not in got["representative"]


def test_must_fail_members_that_disagree_on_a_slot(by_kind):
    got = evaluate(by_kind, "abc", same_as=[("a", "b")], represented_by=[("a", "a")],
                   label=[("a", "x"), ("b", "y"), ("c", "z")], size=[("a", 2), ("b", 2)])
    assert got["identity_conflict"] == {("a", "b", "label"), ("b", "a", "label")}   # size agrees; c is alone
    assert got["class_text"] == {("a", "label", "x"), ("a", "label", "y"), ("c", "label", "z")}
    assert got["class_number"] == {("a", "size", "2")}


def test_two_values_on_one_member_are_no_identity_conflict(by_kind):
    """A slot the domain states twice for one referent is the domain's own functionality, not a merge."""
    assert evaluate(by_kind, "a", label=[("a", "x"), ("a", "y")])["identity_conflict"] == set()


def test_a_shared_value_never_merges(by_kind):
    """Only a same_as claim merges: two referents with the same label stay two classes."""
    got = evaluate(by_kind, "ab", label=[("a", "x"), ("b", "x")])
    assert got["equivalent"] == {("a", "a"), ("b", "b")}


def test_one_direction_only_is_a_failing_control(by_kind):
    """The comparison is sensitive to symmetry: a reference that follows same_as one way only differs."""
    got = evaluate(by_kind, "abc", same_as=[("a", "b"), ("c", "b")])
    one_way = {(x, x) for x in "abc"} | {("a", "b"), ("c", "b")}
    assert got["equivalent"] != one_way


def test_the_view_binds_the_theory_to_a_kind_with_other_names(by_view):
    """The theory's rules are not copied: equivalent reads the view's relation for same_as, which the view fills
    from the domain's own arrow; the recursion runs over it unchanged."""
    assert "item__alias_of" in by_view.relations and "referent__same_as" in by_view.relations
    reads = {a.atom.relation for r in by_view.rules_for("stated_same") for a in r.body}
    assert reads == {"std_identity_referent_same_as"}
    assert by_view.relations["std_identity_referent_same_as"].role == "derived"
    got = evaluate(by_view, "abcde", same_as=[("a", "b"), ("c", "b"), ("d", "e")], represented_by=[("b", "c")],
                   label=[("d", "x"), ("e", "y")])
    assert got["representative"] == {("a", "c"), ("b", "c"), ("c", "c")}
    assert got["representative_not_recorded"] == {("d",), ("e",)}
    assert got["identity_conflict"] == {("d", "e", "label"), ("e", "d", "label")}


NODES = st.sampled_from("abcdefg")
PAIRS = st.sets(st.tuples(NODES, NODES), max_size=8)


@settings(max_examples=60)
@given(same_as=PAIRS, represented_by=st.sets(st.tuples(NODES, NODES), max_size=3),
       label=st.sets(st.tuples(NODES, st.sampled_from("xy")), max_size=5),
       size=st.sets(st.tuples(NODES, st.integers(0, 2)), max_size=5), by=st.sampled_from(["kind", "view"]))
def test_axioms_and_rules_agree_with_the_reference_on_any_claims(same_as, represented_by, label, size, by, by_kind,
                                                                  by_view):
    """Property (Hypothesis): on any claims every engine equals the reference, by kind and by view. equivalent is
    an equivalence relation; where no representative axiom fails, each class has exactly one representative, a
    member, or none recorded."""
    got = evaluate(by_kind if by == "kind" else by_view, "abcdefg", same_as, represented_by, label, size)
    eq = got["equivalent"]
    assert all((x, x) in eq for x in "abcdefg")                                                  # reflexive
    assert all((b, a) in eq for a, b in eq)                                                      # symmetric
    assert all((a, c) in eq for a, b in eq for b2, c in eq if b == b2)                            # transitive
    reps = {}
    for a, r in got["representative"]:
        reps.setdefault(a, set()).add(r)
        assert (a, r) in eq                                                                       # a member
    assert all(len(rs) == 1 for rs in reps.values())                                              # at most one
    assert all(reps[a] == reps[b] for a, b in eq if a in reps and b in reps)                      # one per class
    if not got["representatives_disagree"] and not got["representative_outside_class"]:
        assert set(reps) | {a for (a,) in got["representative_not_recorded"]} == set("abcdefg")
