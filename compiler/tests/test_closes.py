"""`// @closes <relation>` on the minimal, domain-free fixture pack: what the marker becomes in
the rule IR and the bundle, what is refused, and that the invariant it generates finds a key that holds in both
relations, on the batch backend, for the independent checker and, bounded, against Soufflé."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from support import FIXTURE
from rezono_compiler import emit, pack
from rezono_compiler import rules as ir

# Neutral: `wide` holds for a pair whose alpha is large, `narrow` says that an alpha has no such pair. The two
# sizes overlap at 4, so a key can be in both: that is what the generated invariant is for.
RULES = """
.decl wide(a: symbol, b: symbol)
wide(a, b) :- beta__alpha(b, a), alpha__size(a, s), s >= {least}.

// A comment between the marker and the .decl changes nothing.
// @closes wide
.decl narrow(a: symbol)
narrow(a) :- alpha__size(a, s), s < 5.
"""
SOUND, OVERLAP = RULES.format(least=5), RULES.format(least=4)
# The invariant as a pack would write it; Soufflé reads this text, not what the compiler generated.
WRITTEN = "\n.decl narrow_closes_wide(a: symbol)\nnarrow_closes_wide(a) :- narrow(a), wide(a, _).\n"
DATA = {"alpha": [("a1",), ("a2",), ("a3",)], "alpha__size": [("a1", 7), ("a2", 4), ("a3", 2)],
        "beta__alpha": [("b1", "a1"), ("b2", "a2"), ("b3", "a2")]}


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def with_rules(d: Path, text: str) -> Path:
    (d / "rules").mkdir(exist_ok=True)
    (d / "rules" / "core.dl").write_text(text, encoding="utf-8", newline="\n")
    return d


def test_the_marker_is_in_the_ir_and_the_bundle_with_one_generated_invariant(fixture):
    model = pack.read(with_rules(fixture, SOUND))
    prog = ir.load(model.rules)
    assert {n: r.closes for n, r in prog.relations.items() if r.role == "derived"} == {
        "narrow": "wide", "narrow_closes_wide": None, "wide": None}
    check = prog.relations["narrow_closes_wide"]
    assert (check.invariant, check.module, check.key) == (True, "core", prog.relations["narrow"].key)
    # the rule a pack would write: the closing row, and a row of the closed relation at its key, the rest free
    rule = prog.rules["narrow_closes_wide"]
    assert rule.head.terms == ("?a",) and rule.origin == ("rules/core.dl", 7)
    assert [(b.atom.relation, b.atom.terms, b.polarity) for b in rule.body] == [
        ("narrow", ("?a",), "positive"), ("wide", ("?a", "?anon_1"), "positive")]
    assert not (rule.aggregates or rule.conditions or rule.assignments)
    # it changes no world, and the closed relation knows nothing of it
    assert (prog.relations["wide"].world, prog.relations["narrow"].world) == ("closed", "closed")
    doc = ir.to_doc(prog)
    assert ir.to_doc(ir.load(doc)) == doc
    assert [r.get("closes") for r in doc["relations"] if r["role"] == "derived"] == ["wide", None, None]
    files = emit.compile_pack(model)
    assert files == emit.compile_pack(pack.read(fixture))   # the same input gives the same bytes
    relations = {r["id"]: r for r in json.loads(files["bundle/schema-bundle.json"])["relations"]}
    assert relations["narrow"]["closes"] == "wide"
    assert "closes" not in relations["wide"] and "closes" not in relations["narrow_closes_wide"]
    for name in ("engine/rules.sql", "batch/rules.sql"):
        assert '"narrow_closes_wide"' in files[name], name


def test_without_the_marker_nothing_is_added(fixture):
    files = emit.compile_pack(pack.read(with_rules(fixture, SOUND.replace("// @closes wide\n", ""))))
    assert "closes" not in files["ir/rules.json"] and "closes" not in files["bundle/schema-bundle.json"]


def test_the_closing_relation_may_have_every_column_of_the_closed_one(fixture):
    """A prefix may be the whole key: then nothing is projected away and the witness is materialised."""
    text = (".decl wide(a: symbol, n: number)\nwide(a, n) :- alpha__size(a, n), n >= 5.\n"
            "// @closes wide\n.decl narrow(a: symbol, n: number)\nnarrow(a, n) :- alpha__size(a, n), n < 5.\n"
            "// @closes wide\n.decl low(a: symbol)\nlow(a) :- alpha__size(a, 0).\n")
    prog = ir.load(pack.read(with_rules(fixture, text)).rules)
    assert prog.rules["narrow_closes_wide"].body[1].atom.terms == ("?a", "?n")
    assert prog.relations["narrow_closes_wide"].explain == "materialize"
    # several relations may close the same one, each with its own invariant
    assert (prog.relations["low"].closes, prog.relations["low_closes_wide"].invariant) == ("wide", True)
    assert prog.relations["low_closes_wide"].explain == "on_demand"


def closing(marker: str, decl: str = ".decl narrow(a: symbol)", wide: str = ".decl wide(a: symbol, b: symbol)") -> str:
    return (f"{wide}\nwide(a, b) :- beta__alpha(b, a).\n{marker}\n{decl}\nnarrow(a) :- alpha(a).\n")


REFUSED = {
    "unknown-target": (closing("// @closes gamma"), "@closes names another derived relation of the pack, not 'gamma'"),
    "a-table-as-target": (closing("// @closes alpha"), "@closes names another derived relation of the pack, not 'alpha'"),
    "itself": (closing("// @closes narrow"), "@closes names another derived relation of the pack, not 'narrow'"),
    "no-target": (closing("// @closes"), "@closes names one relation, once per .decl"),
    "two-targets": (closing("// @closes wide wide"), "@closes names one relation, once per .decl"),
    "two-markers": (closing("// @closes wide\n// @closes wide"), "@closes names one relation, once per .decl"),
    "on-a-table": ("// @closes alpha\n.decl beta(id: symbol)\n.decl p(x: symbol)\np(x) :- alpha(x).",
                   "@closes is for derived relations, not the table beta"),
    "more-columns-than-the-target": (
        ".decl wide(a: symbol)\nwide(a) :- alpha(a).\n// @closes wide\n.decl narrow(a: symbol, b: symbol)\n"
        "narrow(a, b) :- beta__alpha(b, a).\n", "bad_closes: narrow: its columns are, by position and type, a prefix"),
    "another-type": (
        ".decl wide(a: symbol, n: number)\nwide(a, n) :- alpha__size(a, n).\n// @closes wide\n"
        ".decl narrow(n: number)\nnarrow(n) :- alpha__size(_, n).\n",
        "bad_closes: narrow: its columns are, by position and type, a prefix"),
    "beside-invariant": (closing("// @closes wide\n// @invariant"), "bad_closes: narrow: .* no invariant and no outcome"),
    "beside-outcome": (
        ".decl wide(a: symbol, state: symbol, reason: symbol, b: symbol)\n"
        'wide(a, "known", "", b) :- beta__alpha(b, a).\n// @closes wide\n// @outcome alpha\n'
        '.decl narrow(a: symbol, state: symbol, reason: symbol)\nnarrow(a, "known", "") :- alpha(a).\n',
        "bad_closes: narrow: .* no invariant and no outcome"),
    "the-name-of-the-check-is-taken": (
        closing("// @closes wide") + ".decl narrow_closes_wide(a: symbol)\nnarrow_closes_wide(a) :- alpha(a).\n",
        "narrow_closes_wide is the name of the check that @closes generates"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refused_with_a_clear_error(fixture, case):
    text, message = REFUSED[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(with_rules(fixture, text))


def weakened(doc: dict, how: str) -> dict:
    """The rule IR of SOUND with its generated invariant left out or made weaker by hand."""
    doc = copy.deepcopy(doc)
    rule = next(r for r in doc["rules"] if r["id"] == "narrow_closes_wide")
    relation = next(r for r in doc["relations"] if r["name"] == "narrow_closes_wide")
    if how == "left-out":
        doc["rules"].remove(rule)
        doc["relations"].remove(relation)
    elif how == "not-an-invariant":
        del relation["invariant"]
    elif how == "a-constant-in-the-rest":   # only the rows of one b would be seen
        rule["body"][1]["terms"][1] = "b1"
        rule["witness"]["variables"] = ["?a"]
    elif how == "a-condition":
        rule["conditions"] = [{"op": "ne", "left": "?a", "right": "a2"}]
    elif how == "another-key":   # reads the closed relation at a column that is not the key
        rule["body"][1]["terms"] = ["?anon_1", "?a"]
    return doc


@pytest.mark.parametrize("how", ["left-out", "not-an-invariant", "a-constant-in-the-rest", "a-condition", "another-key"])
def test_a_rule_ir_that_says_closes_carries_the_whole_check(fixture, how):
    """The IR is a contract of its own: a program written by hand cannot say `closes` and leave the invariant
    out, or keep its name and weaken its rule."""
    doc = pack.read(with_rules(fixture, SOUND)).rules
    ir.load(doc)
    with pytest.raises(ir.IRError, match="bad_closes: narrow: closes wide needs the invariant narrow_closes_wide"):
        ir.load(weakened(doc, how))


def test_a_key_in_both_relations_is_a_row_of_the_invariant_for_the_engine_and_the_checker(fixture):
    """The good case is empty and the epoch checks; with the sizes overlapping, a2 is in both relations: the
    invariant holds that key, with a proof like any conclusion, and the independent checker refuses the epoch."""
    pytest.importorskip("duckdb")
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations, load_rules
    from rezono_compiler import batch, explain

    def epoch(text):
        model = pack.read(with_rules(fixture, text))
        prog = ir.load(model.rules)
        con = batch.connect(prog, DATA)
        batch.compute(con, prog, witnesses=True)
        derived = batch.read(con, prog)
        base = [n for n, r in prog.relations.items() if r.role == "base"]
        ex = explain.Explainer(prog, batch.read(con, prog, base) | derived, batch.witnesses(con, prog))
        snaps = {r: ex.snapshot(r).encode() for r in prog.relations}
        manifest = {"id": "m", "snapshots": [
            {"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
             "sha256": hashlib.sha256(b).hexdigest()} for r, b in sorted(snaps.items())]}
        rules = load_rules(model.rules)
        report = check_epoch(ex.chosen(), manifest, rules, snaps.__getitem__,
                             derived=derived_relations(model.rules, rules))
        return derived, report

    derived, report = epoch(SOUND)
    assert derived["narrow_closes_wide"] == set() and derived["narrow"] == {("a2",), ("a3",)}
    assert report["valid"] and not report["findings"], report["findings"]
    derived, report = epoch(OVERLAP)
    assert derived["narrow_closes_wide"] == {("a2",)}   # once, though a2 has two rows in wide
    found = {(f["reason"], f.get("relation")) for f in report["findings"] if f["severity"] == "error"}
    assert not report["valid"] and found == {("invariant_violated", "narrow_closes_wide")}


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
@pytest.mark.parametrize("seed", range(8))
def test_the_generated_invariant_equals_the_written_rule_on_souffle(fixture, seed, tmp_path):
    """The bounded oracle check, per pull request: over generated facts, what the batch backend derives from
    the generated rule is what Soufflé derives from the IR, and from the text with the invariant written out by
    hand. The sizes overlap, so the invariant has rows to agree on."""
    pytest.importorskip("duckdb")
    import random

    import souffle
    from rezono_compiler import batch

    prog = ir.load(pack.read(with_rules(fixture, OVERLAP)).rules)
    rnd = random.Random(seed)
    alphas = [f"a{i}" for i in range(8)]
    data = {"alpha": [(a,) for a in alphas], "alpha__size": [("a0", 4)] + [(a, rnd.randrange(10)) for a in alphas[1:]],
            "beta__alpha": sorted({("b0", "a0")} | {(f"b{rnd.randrange(1, 12)}", rnd.choice(alphas)) for _ in range(12)})}
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    derived = batch.read(con, prog)
    assert ("a0",) in derived["narrow_closes_wide"]
    assert derived["narrow_closes_wide"] == derived["narrow"] & {(a,) for a, _ in derived["wide"]}
    assert souffle.run(prog, data, tmp_path) == derived
    assert souffle.run(prog, data, tmp_path, program_text=souffle.source(prog, [OVERLAP + WRITTEN])) == derived
