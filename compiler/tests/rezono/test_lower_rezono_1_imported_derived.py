"""The `rezono 1` derivations of an imported pack lower in the importer's compile, and the importer reads them
(decisions/language-rezono-1.md sections 2, 4, 5.5 and 8 step 5; decisions/language-rezono-1-refinements.md
section 1).

Every standard pack reaches its readers through an import, so its conversion to `rezono 1`
(examples/test_rezono_1_pack_conversion.py, one case per pack) needs this first: today
compiler/rezono_compiler/rezono_derived.py refuses a derivation of an imported pack with R049, and a `rezono 1`
derivation may call only relations derived in its own pack.

The pack `lib` declares the derivations; the importers hold the facts. Every expected row below is written by hand
from the same rules as compiler/tests/rezono/test_lower_rezono_1_derived.py:
- a slot path gives `known` with the slot's value;
- `S.count(pred)` counts the rows where `pred` is true and gives `known 0` for none;
- `S.one(expr)` declared `T?` gives `known` for one distinct value, `invalid multiple_values` for more than one and
  `not_applicable no_match` for none;
- a `Bool` derivation is a plain set, and a functional one has exactly one `(key..., state, reason, value)` row per
  key of its closed domain;
- a derivation `over` an imported Bool set has one row per tuple of that set, as over a set of its own pack.
DuckDB runs the compiled importer; Soufflé, where installed, runs the same rule IR as the independent oracle."""

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

LIB = """\
rezono 1
pack lib

kind Area
kind Item
  area: Area
kind Choice
  owner: Item
  area: Area
  target: Item

extend s: Item
  derived home: Area = s.area
  derived chooses: Int = Choice.count(owner = s)

derived asks(a: Item, r: Area): Bool = a.area = r

derived chosen(a: Item, r: Area): Item?
  over asks(a, r)
  = Choice.where(owner = a and area = r).one(target)
"""
LIB_CHANNELS = """\
kinds:
  - {kind: area, shape: rect}
  - {kind: item, shape: ellipse}
  - {kind: choice, shape: pill}
arrows: []
"""
LIB_LABELS = "area: gebied\nitem: ding\nchoice: keuze\n"

FACTS = """\
area:
  - {id: north}
  - {id: south}
  - {id: east}
item:
  - {id: ann, area: north}
  - {id: bob, area: north}
  - {id: cid, area: south}
  - {id: dan, area: east}
choice:
  - {id: c1, owner: ann, area: north, target: bob}
  - {id: c2, owner: cid, area: south, target: ann}
  - {id: c3, owner: cid, area: south, target: bob}
"""
FACT_SOURCE = ('default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
               'position: compiler/tests/rezono/test_lower_rezono_1_imported_derived.py#FACTS}\n')

# A Datalog importer reads a Bool derivation and a functional one, as (key..., state, reason, value).
DATALOG_READER = """\
.decl north_asker(a: symbol)
north_asker(a) :- asks(a, "north").
.decl settled(a: symbol, r: symbol, t: symbol)
settled(a, r, t) :- chosen(a, r, "known", _, t).
.decl conflicted(a: symbol, r: symbol)
conflicted(a, r) :- chosen(a, r, "invalid", "multiple_values", _).
.output north_asker, settled, conflicted
"""
# A rezono 1 importer calls an imported Bool derivation, also negated, and derives a functional value over it.
REZONO_1_READER = """\
rezono 1
pack minimal
use lib

derived also_asks(a: Item, r: Area): Bool = asks(a, r)
derived elsewhere(a: Item, r: Area): Bool = not asks(a, r)

derived pick(a: Item, r: Area): Item?
  over asks(a, r)
  = Choice.where(owner = a and area = r).one(target)
"""
# Counter-case: a call to a relation that neither pack declares stays refused.
REZONO_1_STRAY = """\
rezono 1
pack minimal
use lib

derived stray(a: Item): Bool = nowhere(a)
"""

IMPORTED = {"asks", "item_home", "item_chooses", "chosen"}
# (key..., state, reason) per row of each imported functional derivation; KNOWN holds the value of each known row.
EXPECTED = {
    # s.area: every item has its area.
    "item_home": {("ann", "known", ""), ("bob", "known", ""), ("cid", "known", ""), ("dan", "known", "")},
    # Choice.count(owner = s): none -> known 0.
    "item_chooses": {("ann", "known", ""), ("bob", "known", ""), ("cid", "known", ""), ("dan", "known", "")},
    # Choice.where(owner = a and area = r).one(target) over asks, declared Item?.
    "chosen": {("ann", "north", "known", ""), ("bob", "north", "not_applicable", "no_match"),
               ("cid", "south", "invalid", "multiple_values"), ("dan", "east", "not_applicable", "no_match")},
}
KNOWN = {
    "item_home": {("ann",): "north", ("bob",): "north", ("cid",): "south", ("dan",): "east"},
    "item_chooses": {("ann",): "1", ("bob",): "0", ("cid",): "2", ("dan",): "0"},
    "chosen": {("ann", "north"): "bob"},
}
ASKS = {("ann", "north"), ("bob", "north"), ("cid", "south"), ("dan", "east")}
DATALOG_ROWS = {
    "north_asker": {("ann",), ("bob",)},
    "settled": {("ann", "north", "bob")},
    "conflicted": {("cid", "south")},
}
AREAS = ("north", "south", "east")
ITEMS = ("ann", "bob", "cid", "dan")
REZONO_1_ROWS = {
    "also_asks": ASKS,
    # Every item and area that asks does not hold: four items by three areas, less the four of ASKS.
    "elsewhere": {(item, area) for item in ITEMS for area in AREAS} - ASKS,
}
# What a relation declaration says about its meaning, compared between `lib` alone and `lib` imported.
DECLARED = ("role", "key", "domain", "value", "world", "conflict_policy")


class MissingImportedRezono1Derivations(AssertionError):
    """An importer does not lower or read the rezono 1 derivations of an imported pack."""


def _author(directory: Path, stem: str, source: str) -> dict:
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    module, form = folder / f"{stem}.rezono", folder / f"{stem}.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(form.read_bytes())["format"] == "rezono.module/5"
    return {"module": f"rezono/{stem}.rezono", "form": f"rezono/{stem}.json", "layer": "facts"}


def _lib(root: Path) -> Path:
    """The pack `lib`: the fixture's messages, no schema of its own, and the rezono 1 module LIB."""
    directory = Path(shutil.copytree(FIXTURE, root / "lib"))
    shutil.rmtree(directory / "schema")
    (directory / "channels.yaml").write_text(LIB_CHANNELS, encoding="utf-8", newline="\n")
    (directory / "labels" / "nl.yaml").write_text(LIB_LABELS, encoding="utf-8", newline="\n")
    meta = yaml.safe_load((directory / "pack.yaml").read_bytes())
    meta["name"] = "lib"
    meta["rezono"] = [_author(directory, "derived", LIB)]
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return directory


def _importer(root: Path, lib: Path, name: str, *, datalog: str | None = None, module: str | None = None) -> Path:
    """The fixture pack beside `lib`, pinning it, with the facts and a Datalog rule file or a rezono 1 module."""
    directory = Path(shutil.copytree(FIXTURE, root / name))
    meta = yaml.safe_load((directory / "pack.yaml").read_bytes())
    meta["imports"] = [{"name": "lib", "path": "../lib", "sha256": modules.pack_hash(lib)}]
    (directory / "facts").mkdir()
    (directory / "facts/case.yaml").write_text(FACTS, encoding="utf-8", newline="\n")
    (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    if datalog is not None:
        (directory / "rules").mkdir()
        (directory / "rules/reads.dl").write_text(datalog, encoding="utf-8", newline="\n")
    if module is not None:
        meta["rezono"] = [_author(directory, "reads", module)]
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return directory


def _compiled(directory: Path):
    """The model, the rule IR document and the loaded program of a pack, or the refusal as the test's failure."""
    try:
        model = pack.read(directory)
        files = emit.compile_pack(model)
    except pack.CompileError as error:
        found = "; ".join(f"{d.code} {d.message}" for d in getattr(error, "diagnostics", ())) or str(error)
        raise MissingImportedRezono1Derivations(f"{directory.name}: {found}") from error
    if "ir/rules.json" not in files:
        raise MissingImportedRezono1Derivations(f"{directory.name}: no ir/rules.json among {sorted(files)}")
    document = json.loads(files["ir/rules.json"])
    try:
        program = rules.load(document)
    except rules.IRError as error:
        raise MissingImportedRezono1Derivations(f"{directory.name}: rules.load: {error}") from error
    return model, document, program


def _run(directory: Path, model, program, tmp_path: Path) -> tuple[dict, list]:
    """The derived rows on DuckDB, and every difference from Soufflé where it is installed."""
    rows = dict(scenarios.states(model, directory))["0-case"]
    con, _, _ = batch.run(model, program, rows)
    derived = batch.read(con, program)
    problems = []
    if shutil.which("souffle"):
        oracle = souffle.run(program, scenarios.rule_rows(model, program, rows), tmp_path / f"souffle-{directory.name}")
        for name in sorted(set(oracle) | set(derived)):
            if oracle.get(name) != derived.get(name):
                problems.append({"souffle": name, "oracle": sorted(oracle.get(name, ())),
                                 "duckdb": sorted(derived.get(name, ()))})
    return derived, problems


def _imported_problems(document: dict, alone: dict, derived: dict) -> list:
    """How the imported derivations in an importer differ from `lib` alone and from the hand-written rows."""
    problems: list = []
    relations = {relation["name"]: relation for relation in document.get("relations", [])}
    own = {relation["name"]: relation for relation in alone.get("relations", [])}
    for name in sorted(IMPORTED):
        if name not in relations:
            problems.append({"imported relation missing": name, "relations": sorted(relations)})
            continue
        found = {member: relations[name].get(member) for member in DECLARED}
        expected = {member: own[name].get(member) for member in DECLARED}
        if found != expected:
            problems.append({name: {"imported": found, "in lib": expected}})
    for name, expected in EXPECTED.items():
        keys = len(next(iter(expected))) - 2
        states = {row[:keys + 2] for row in derived.get(name, set())}
        known = {row[:keys]: row[keys + 2] for row in derived.get(name, set()) if row[keys] == "known"}
        if states != expected:
            problems.append({name: {"missing": sorted(expected - states), "unexpected": sorted(states - expected)}})
        if known != KNOWN[name]:
            problems.append({name: {"known values": sorted(known.items()), "expected": sorted(KNOWN[name].items())}})
    if derived.get("asks") != ASKS:
        problems.append({"asks": sorted(derived.get("asks", ()))})
    return problems


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: sections 5.5 (cross-pack consumers) and 8 step 5. Lower the rezono 1 "
        "derivations of an imported pack in the importer's compile; compiler/rezono_compiler/rezono_derived.py "
        "refuses them today with R049 \"a derivation of an imported rezono 1 pack is not lowered yet\". Each keeps "
        "the relation name, role, key, closed domain, value and conflict policy it has when its own pack compiles, "
        "gives the rows written by hand here on the importer's facts (on DuckDB and, where installed, Soufflé), and "
        "a Datalog rule of the importer reads it, a functional derivation as (key..., state, reason, value). Every "
        "standard pack reaches its readers through an import, so each conversion case in "
        "examples/test_rezono_1_pack_conversion.py names this test as its prerequisite."
    ),
)
def test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack(tmp_path):
    lib = _lib(tmp_path)
    alone = json.loads(emit.compile_pack(pack.read(lib))["ir/rules.json"])
    assert IMPORTED <= {relation["name"] for relation in alone["relations"]}, "lib alone lowers its derivations"

    importer = _importer(tmp_path, lib, "datalog", datalog=DATALOG_READER)
    model, document, program = _compiled(importer)
    derived, problems = _run(importer, model, program, tmp_path)
    problems += _imported_problems(document, alone, derived)
    for name, expected in DATALOG_ROWS.items():
        if derived.get(name) != expected:
            problems.append({name: {"rows": sorted(derived.get(name, ())), "expected": sorted(expected)}})
    if problems:
        raise MissingImportedRezono1Derivations(json.dumps(problems, indent=1, default=str))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: sections 2 and 5.5, with decisions/language-rezono-1-refinements.md "
        "section 1. Let a rezono 1 derivation read a relation of a pack it imports with `use`: a call to an "
        "imported Bool derivation, also negated, and a functional derivation `over` an imported Bool set; "
        "compiler/rezono_compiler/rezono_derived.py accepts only relations derived in the pack itself today "
        "(R001, and `over` names a set this pack derives). A call to a relation that neither pack declares stays "
        "refused with R001. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_imported_derived.py"
        "--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack."
    ),
)
def test_a_rezono_1_derivation_reads_a_relation_of_an_imported_pack(tmp_path):
    lib = _lib(tmp_path)
    alone = json.loads(emit.compile_pack(pack.read(lib))["ir/rules.json"])

    importer = _importer(tmp_path, lib, "native", module=REZONO_1_READER)
    model, document, program = _compiled(importer)
    derived, problems = _run(importer, model, program, tmp_path)
    problems += _imported_problems(document, alone, derived)
    for name, expected in REZONO_1_ROWS.items():
        if derived.get(name) != expected:
            problems.append({name: {"rows": sorted(derived.get(name, ())), "expected": sorted(expected)}})
    # `pick` over the imported asks is `chosen` of lib, derived in the importer.
    relations = {relation["name"]: relation for relation in document.get("relations", [])}
    if relations.get("pick", {}).get("domain") != "asks":
        problems.append({"pick": {"domain": relations.get("pick", {}).get("domain")}})
    picked = {row[:4] for row in derived.get("pick", set())}
    picked_known = {row[:2]: row[4] for row in derived.get("pick", set()) if row[2] == "known"}
    if picked != EXPECTED["chosen"] or picked_known != KNOWN["chosen"]:
        problems.append({"pick": {"rows": sorted(derived.get("pick", ())), "expected": sorted(EXPECTED["chosen"])}})

    # Counter-case: a relation that neither the importer nor `lib` declares.
    stray = _importer(tmp_path, lib, "stray", module=REZONO_1_STRAY)
    try:
        emit.compile_pack(pack.read(stray))
        problems.append({"stray": "a call to an undeclared relation compiled"})
    except pack.CompileError as error:
        codes = {d.code for d in getattr(error, "diagnostics", ())}
        if "R001" not in codes:
            problems.append({"stray": sorted(codes) or str(error)})
    if problems:
        raise MissingImportedRezono1Derivations(json.dumps(problems, indent=1, default=str))
