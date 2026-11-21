"""One strict red test per `rezono 1` rule construct that the standard packs' legacy rules use and that
compiler/rezono_compiler/rezono_derived.py does not lower yet (decisions/language-rezono-1.md sections 2, 4, 6
and 8 step 5; decisions/language-rezono-1-refinements.md section 1; decisions/language-native-rules.md,
annotations and table of observed forms).

Each standard pack converts once from Datalog to `rezono 1` and must publish the same meaning
(examples/test_rezono_1_pack_conversion.py, one case per pack). So each construct here is written twice over the
same kinds and facts: as a `rezono 1` derivation, and as the Datalog twin that the standard packs use today. The
`rezono 1` form must compile, declare each relation as its twin does (role, key, world, and the `invariant`,
`absence`, `outcome`, `extend` and `explain` options), and derive the rows written by hand below, which are the
rows the twin derives. Each test needs exactly one construct beyond what lowers today: without the construct,
the same derivation compiles (checked while writing these tests), so one worker can make each test green alone.
DuckDB runs both packs; Soufflé, where installed, runs the `rezono 1` rule IR as the independent oracle."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

import souffle
from expression_packs import ROOT
from rezono_compiler import batch, emit, modules, pack, rules, scenarios
from support import FIXTURE

KINDS = """\
rezono 1
pack minimal

kind Area
kind Item
  area: Area
  rank: Int?
  next: Item?
  links: Item*
kind Entry
  budget: Text
  cell: Text
  ceiling: Int
kind Span
  start: Int
  end: Int
kind Household
kind Statement world open
  household: Household
"""
FACTS = """\
area:
  - {id: north}
  - {id: south}
  - {id: east}
item:
  - {id: i1, area: north, rank: 1, next: i2, links: [i2, i3]}
  - {id: i2, area: north, rank: 5, next: i2, links: [i3]}
  - {id: i3, area: south, rank: 3, next: i1}
  - {id: i4, area: east}
entry:
  - {id: e1, budget: b1, cell: c1, ceiling: 5}
  - {id: e2, budget: b1, cell: c2, ceiling: 3}
  - {id: e3, budget: b2, cell: c1, ceiling: 7}
span:
  - {id: s1, start: 1, end: 10}
  - {id: s2, start: 4, end: 6}
  - {id: s3, start: 12, end: 20}
household:
  - {id: h1}
  - {id: h2}
  - {id: h3}
statement:
  - {id: st1, household: h1}
  - {id: st2, household: h3}
"""
FACT_SOURCE = ('default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
               'position: compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py#FACTS}\n')
REASON_MESSAGE = "reason.statement_not_received = {{Voor {$household} is geen verklaring ontvangen.}}\n"
KIND_SIGNS = ("area", "item", "entry", "span", "household", "statement")

# What a relation declaration says, compared between a rezono 1 derivation and its Datalog twin.
DECLARED = ("role", "key", "world", "invariant", "absence", "outcome", "extend")


class MissingRezono1RuleConstruct(AssertionError):
    """A rezono 1 rule construct does not lower to rezono.rules/2 as its Datalog twin does."""


def _author(directory: Path, stem: str, source: str) -> dict:
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    module, form = folder / f"{stem}.rezono", folder / f"{stem}.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise MissingRezono1RuleConstruct(f"the reader refuses {directory.name}: {result.stderr or result.stdout}")
    assert json.loads(form.read_bytes())["format"] == "rezono.module/5"
    return {"module": f"rezono/{stem}.rezono", "form": f"rezono/{stem}.json", "layer": "facts"}


def _pack(root: Path, name: str, module: str, *, datalog: str | None = None, facts: bool = True,
          lib: Path | None = None) -> Path:
    """The fixture pack with the module `module`, optionally a Datalog rule file, the facts, and a pin on `lib`."""
    directory = Path(shutil.copytree(FIXTURE, root / name))
    meta = yaml.safe_load((directory / "pack.yaml").read_bytes())
    if lib is not None:
        meta["imports"] = [{"name": "lib", "path": f"../{lib.name}", "sha256": modules.pack_hash(lib)}]
    if facts:
        (directory / "facts").mkdir()
        (directory / "facts/case.yaml").write_text(FACTS, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8", newline="\n") as messages:
        messages.write(REASON_MESSAGE)
    if module:
        meta["rezono"] = [_author(directory, "m", module)]
    if datalog is not None:
        (directory / "rules").mkdir()
        (directory / "rules/twin.dl").write_text(datalog, encoding="utf-8", newline="\n")
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return directory


def _lib(root: Path, name: str, module: str, *, datalog: str | None = None) -> Path:
    """A fact-free pack `lib` holding the kinds, for the `extend` test: its importer writes the clauses."""
    directory = Path(shutil.copytree(FIXTURE, root / name))
    shutil.rmtree(directory / "schema")
    (directory / "channels.yaml").write_text(
        "kinds:\n" + "".join(f"  - {{kind: {kind}, shape: rect}}\n" for kind in KIND_SIGNS) + "arrows: []\n",
        encoding="utf-8", newline="\n")
    (directory / "labels/nl.yaml").write_text("".join(f"{kind}: {kind}\n" for kind in KIND_SIGNS),
                                              encoding="utf-8", newline="\n")
    meta = yaml.safe_load((directory / "pack.yaml").read_bytes())
    meta["name"] = "lib"
    meta["rezono"] = [_author(directory, "m", module.replace("pack minimal", "pack lib", 1))]
    if datalog is not None:
        (directory / "rules").mkdir()
        (directory / "rules/lib.dl").write_text(datalog, encoding="utf-8", newline="\n")
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return directory


def _run(directory: Path, tmp_path: Path, *, oracle: bool) -> tuple[dict, dict, list]:
    """The rule IR by relation name, the derived rows on DuckDB, and every difference from Soufflé."""
    try:
        model = pack.read(directory)
        files = emit.compile_pack(model)
    except pack.CompileError as error:
        found = "; ".join(f"{d.code} {d.message}" for d in getattr(error, "diagnostics", ())) or str(error)
        raise MissingRezono1RuleConstruct(f"{directory.name}: {found}") from error
    if "ir/rules.json" not in files:
        raise MissingRezono1RuleConstruct(f"{directory.name}: no ir/rules.json among {sorted(files)}")
    document = json.loads(files["ir/rules.json"])
    try:
        program = rules.load(document)
    except rules.IRError as error:
        raise MissingRezono1RuleConstruct(f"{directory.name}: rules.load: {error}") from error
    rows = dict(scenarios.states(model, directory))["0-case"]
    con, _, _ = batch.run(model, program, rows)
    derived = batch.read(con, program)
    problems = []
    if oracle and shutil.which("souffle"):
        found = souffle.run(program, scenarios.rule_rows(model, program, rows), tmp_path / f"souffle-{directory.name}")
        for name in sorted(set(found) | set(derived)):
            if found.get(name) != derived.get(name):
                problems.append({"souffle": name, "oracle": sorted(found.get(name, ())),
                                 "duckdb": sorted(derived.get(name, ()))})
    return {relation["name"]: relation for relation in document["relations"]}, derived, problems


def _compare(native: Path, twin: Path, expected: dict, tmp_path: Path, *, declared=DECLARED) -> None:
    """Hold the rezono 1 pack to its Datalog twin and to the rows written by hand."""
    twin_relations, twin_rows, _ = _run(twin, tmp_path, oracle=False)
    for name, rows in expected.items():  # the hand-written rows are the twin's: a check on this test itself
        assert twin_rows.get(name) == rows, (name, sorted(twin_rows.get(name, ())))
    relations, derived, problems = _run(native, tmp_path, oracle=True)
    for name, rows in expected.items():
        if name not in relations:
            problems.append({"missing relation": name, "relations": sorted(relations)})
            continue
        found = {member: relations[name].get(member) for member in declared}
        want = {member: twin_relations[name].get(member) for member in declared}
        if found != want:
            problems.append({name: {"rezono 1": found, "Datalog twin": want}})
        if derived.get(name) != rows:
            problems.append({name: {"rows": sorted(derived.get(name, ())), "expected": sorted(rows)}})
    if problems:
        raise MissingRezono1RuleConstruct(json.dumps(problems, indent=1, default=str))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 8 step 5, with decisions/language-native-rules.md "
        "(annotations). Lower the `invariant` option of a rezono 1 Bool derivation (`derived p(...): Bool invariant "
        "= ...`) as the Datalog @invariant: the relation declares invariant true and keeps its rows. "
        "compiler/rezono_compiler/rezono_derived.py refuses it today with R049 \"`options` on a rezono 1 derivation "
        "is not lowered yet\"; the same derivation without the option compiles. The standard packs std-decision, "
        "std-identity, std-loop, std-order, std-part, std-review and std-time and front-door example packs need it."
    ),
)
def test_rezono_1_invariant_option_lowers_as_the_datalog_invariant(tmp_path):
    native = _pack(tmp_path, "native", KINDS + "\nderived self_linked(a: Item): Bool invariant = a.next = a\n")
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        "// @invariant\n.decl self_linked(a: symbol)\nself_linked(a) :- item__next(a, a).\n"))
    _compare(native, twin, {"self_linked": {("i2",)}}, tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 8 step 5, with decisions/language-native-rules.md "
        "(annotations). Lower the `explain` option of a rezono 1 Bool derivation as the Datalog @explain: with "
        "`explain on_demand` the relation declares that explain mode, with `explain fold` the pack folds it "
        "(pack.folds, display only), and both keep their rows. "
        "compiler/rezono_compiler/rezono_derived.py refuses it today with R049 \"`options` on a rezono 1 "
        "derivation is not lowered yet\"; the same derivation without the option compiles. The standard packs "
        "std-identity, std-order and std-time need it."
    ),
)
def test_rezono_1_explain_option_lowers_as_the_datalog_explain(tmp_path):
    native = _pack(tmp_path, "native", KINDS + (
        "\nderived pointed(a: Item, b: Item): Bool explain fold = a.next = b\n"
        "derived next_of(a: Item, b: Item): Bool explain on_demand = pointed(a, b)\n"))
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        "// @explain fold\n.decl pointed(a: symbol, b: symbol)\npointed(a, b) :- item__next(a, b).\n"
        "// @explain on_demand\n.decl next_of(a: symbol, b: symbol)\nnext_of(a, b) :- pointed(a, b).\n"))
    pairs = {("i1", "i2"), ("i2", "i2"), ("i3", "i1")}
    _compare(native, twin, {"next_of": pairs, "pointed": pairs}, tmp_path, declared=(*DECLARED, "explain"))
    folded = {name for name in ("next_of", "pointed") if name in pack.read(native).folds}
    assert {name for name in ("next_of", "pointed") if name in pack.read(twin).folds} == {"pointed"}
    if folded != {"pointed"}:
        raise MissingRezono1RuleConstruct(f"folded relations: {sorted(folded)}, expected ['pointed']")


EXTEND_MODULE = """
derived stated(a: Item, b: Item): Bool extend
derived ahead(a: Item, b: Item): Bool = stated(a, b) or a.next = b
"""
EXTEND_TWIN = """\
// @extend
.decl stated(a: symbol, b: symbol)
.decl ahead(a: symbol, b: symbol)
ahead(a, b) :- stated(a, b).
ahead(a, b) :- item__next(a, b).
"""
# The importer's clause of the extension point, as examples/platform writes stated_precedes of std-order.
EXTEND_CLAUSE = "stated(a, b) :- item__rank(a, x), item__rank(b, y), x < y.\n"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: sections 5.5 and 8 step 5, with decisions/language-native-rules.md "
        "(annotations). Lower the `extend` option on a rezono 1 Bool derivation without `=` "
        "(`derived p(...): Bool extend`) as the Datalog @extend: alone it denotes the empty set, a pack that imports "
        "it writes its clauses, and derivations of its own pack read them. "
        "compiler/rezono_compiler/rezono_derived.py refuses both today with R049. The standard packs std-access, "
        "std-identity, std-loop and std-order need it. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_imported_derived.py"
        "--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack."
    ),
)
def test_rezono_1_extend_option_lowers_as_the_datalog_extension_point(tmp_path):
    native_lib = _lib(tmp_path, "native-lib", KINDS + EXTEND_MODULE)
    twin_lib = _lib(tmp_path, "twin-lib", KINDS, datalog=EXTEND_TWIN)
    native = _pack(tmp_path, "native", "", datalog=EXTEND_CLAUSE, lib=native_lib)
    twin = _pack(tmp_path, "twin", "", datalog=EXTEND_CLAUSE, lib=twin_lib)
    _compare(native, twin, {
        "stated": {("i1", "i2"), ("i1", "i3"), ("i3", "i2")},
        "ahead": {("i1", "i2"), ("i1", "i3"), ("i2", "i2"), ("i3", "i1"), ("i3", "i2")},
    }, tmp_path)
    # Alone, the extension point of lib is declared and empty.
    relations, derived, _ = _run(_pack(tmp_path, "alone", KINDS + EXTEND_MODULE), tmp_path, oracle=False)
    if relations.get("stated", {}).get("extend") is not True or derived.get("stated"):
        raise MissingRezono1RuleConstruct(f"alone: {relations.get('stated')}, {sorted(derived.get('stated', ()))}")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1-refinements.md: section 1. Lower an existential `Kind.any(pred)` and "
        "`Kind.any(x: pred)` in a rezono 1 Bool derivation, also one that binds scalar parameters "
        "(`derived has_entry(b: Text, c: Text): Bool = Entry.any(budget = b and cell = c)`) and one that recurses "
        "(`reaches(a, b) = a.next = b or Item.any(m: reaches(a, m) and m.next = b)`), as the Datalog join with a "
        "body-only variable. compiler/rezono_compiler/rezono_derived.py refuses it today with R049 \"this Bool "
        "expression is not lowered to rezono.rules/2 yet\". Every standard pack with rules except std-order needs "
        "it, and so do front-door example packs."
    ),
)
def test_rezono_1_any_lowers_as_an_existential_join(tmp_path):
    native = _pack(tmp_path, "native", KINDS + (
        "\nderived has_entry(b: Text, c: Text): Bool = Entry.any(budget = b and cell = c)\n"
        "derived reaches(a: Item, b: Item): Bool = a.next = b or Item.any(m: reaches(a, m) and m.next = b)\n"))
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        ".decl has_entry(b: symbol, c: symbol)\nhas_entry(b, c) :- entry__budget(e, b), entry__cell(e, c).\n"
        ".decl reaches(a: symbol, b: symbol)\nreaches(a, b) :- item__next(a, b).\n"
        "reaches(a, b) :- reaches(a, m), item__next(m, b).\n"))
    _compare(native, twin, {
        "has_entry": {("b1", "c1"), ("b1", "c2"), ("b2", "c1")},
        "reaches": {("i1", "i2"), ("i2", "i2"), ("i3", "i1"), ("i3", "i2")},
    }, tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 8 step 5, with decisions/language-rezono-1-refinements.md "
        "section 1. Lower membership in a multivalued slot (`b in a.links`) in a rezono 1 Bool derivation, alone "
        "and in a conjunction, as the Datalog read of the slot table. compiler/rezono_compiler/rezono_derived.py "
        "refuses it today with R049 \"this Bool expression is not lowered to rezono.rules/2 yet\"; a comparison of "
        "two slot paths (`a.area = b.area`) already lowers. The standard packs std-decision, std-identity and "
        "std-order need it."
    ),
)
def test_rezono_1_membership_in_a_multivalued_slot_lowers(tmp_path):
    native = _pack(tmp_path, "native", KINDS + (
        "\nderived linked(a: Item, b: Item): Bool = b in a.links\n"
        "derived linked_near(a: Item, b: Item): Bool = b in a.links and a.area = b.area\n"))
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        ".decl linked(a: symbol, b: symbol)\nlinked(a, b) :- item__links(a, b).\n"
        ".decl linked_near(a: symbol, b: symbol)\n"
        "linked_near(a, b) :- item__links(a, b), item__area(a, r), item__area(b, r).\n"))
    _compare(native, twin, {
        "linked": {("i1", "i2"), ("i1", "i3"), ("i2", "i3")},
        "linked_near": {("i1", "i2")},
    }, tmp_path)


def test_rezono_1_arithmetic_in_a_bool_derivation_lowers(tmp_path):
    native = _pack(tmp_path, "native", KINDS + (
        "\nderived long(s: Span): Bool = s.end > s.start + 5\n"
        "derived soon_after(s: Span, t: Span): Bool = t.start > s.end and t.start <= s.end + 2\n"))
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        ".decl long(s: symbol)\nlong(s) :- span__start(s, a), span__end(s, e), t = a + 5, e > t.\n"
        ".decl soon_after(s: symbol, t: symbol)\n"
        "soon_after(s, t) :- span__end(s, e), span__start(t, x), x > e, w = e + 2, x <= w.\n"))
    _compare(native, twin, {"long": {("s1",), ("s3",)}, "soon_after": {("s1", "s3")}}, tmp_path)


def test_rezono_1_count_in_a_bool_derivation_lowers(tmp_path):
    native = _pack(tmp_path, "native", KINDS + "\nderived crowded(g: Area): Bool = Item.count(area = g) >= 2\n")
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        ".decl crowded(g: symbol)\ncrowded(g) :- area(g), n = count : { item__area(_, g) }, n >= 2.\n"))
    _compare(native, twin, {"crowded": {("north",)}}, tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 5.11 (proposal only — NOT READY, do not pick up until "
        "section 5.11 is decided). Spell the Datalog @absence and @outcome as the options `absence` and "
        "`outcome K` of a rezono 1 Bool derivation, with the meaning they have on a rezono 0 rule signature "
        "(decisions/language-native-rules.md, annotations), and lower them so that the relations declare "
        "absence true and outcome K and keep their rows and checks. The reader refuses both options on "
        "`derived` today. std-decision, std-time and front-door example packs need them. "
        "Waits for the decision settling the section 5.11 proposal in decisions/language-rezono-1.md, and for "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py"
        "--test_rezono_1_any_lowers_as_an_existential_join."
    ),
)
def test_rezono_1_absence_and_outcome_options_lower_as_the_datalog_annotations(tmp_path):
    native = _pack(tmp_path, "native", KINDS + (
        "\nderived has_statement(h: Household): Bool = Statement.any(household = h)\n"
        "derived statement_not_received(h: Household): Bool absence = not has_statement(h)\n"
        "derived assessed(h: Household, state: Text, reason: Text): Bool outcome Household\n"
        "  = (statement_not_received(h) and state = \"unknown\" and reason = \"statement_not_received\")"
        " or (not statement_not_received(h) and state = \"known\" and reason = \"\")\n"))
    twin = _pack(tmp_path, "twin", KINDS, datalog=(
        ".decl has_statement(h: symbol)\nhas_statement(h) :- statement__household(_, h).\n"
        "// @absence\n.decl statement_not_received(h: symbol)\n"
        "statement_not_received(h) :- household(h), !has_statement(h).\n"
        "// @outcome household\n.decl assessed(h: symbol, state: symbol, reason: symbol)\n"
        "assessed(h, \"unknown\", \"statement_not_received\") :- statement_not_received(h).\n"
        "assessed(h, \"known\", \"\") :- household(h), !statement_not_received(h).\n"))
    _compare(native, twin, {
        "has_statement": {("h1",), ("h3",)},
        "statement_not_received": {("h2",)},
        "assessed": {("h1", "known", ""), ("h2", "unknown", "statement_not_received"), ("h3", "known", "")},
    }, tmp_path)
