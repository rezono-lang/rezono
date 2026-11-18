"""A pack import brings its calculation definitions, and the evaluation date is the importing
pack's: a theory with one calculation, two importing packs with their own dates and parameter
facts, and the same definition written in one pack. Neutral names; it describes no domain."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from calcsupport import run_both
from rezono_compiler import calc, calc_sql, emit, modules, pack, scenarios
from rezono_compiler.pack import CompileError
from support import FIXTURE, REPO

THEORY = "shared-calc"
CHOICE = {"name": "name", "valid_from": "valid_from", "valid_until": "valid_until", "known_from": "known_from"}
BINDINGS = {"format": "rezono.calc/1", "subject": "item", "parameters": "setting.value", "parameter_choice": CHOICE}
# What each importing pack states and holds: its evaluation date and its parameter rows
# (element, name, value, valid_from, valid_until, known_from).
CONSUMERS = {
    "one": ("2025-06-01", [("rate-2025", "rate", 15, "2025-01-01", "2026-01-01", "2024-12-01"),
                           ("rate-2026", "rate", 25, "2026-01-01", "2027-01-01", "2025-12-01")]),
    "two": ("2026-06-01", [("rate-2025", "rate", 40, "2025-01-01", "2026-01-01", "2024-12-01"),
                           ("rate-2026", "rate", 50, "2026-01-01", "2027-01-01", "2025-12-01")]),
}


def share(version: str, valid: tuple[str, str], known: str, rounding: str) -> dict:
    """One version of the one calculation: a share of an attribute at a rate that is a parameter, rounded,
    plus a count that the theory's own rules derive."""
    rated = {"op": rounding, "args": [{"op": "ratio", "args": [{"fact": "item.amount"}, {"parameter": "rate"},
                                                             {"integer": "100"}]}]}
    return {"id": f"share@{version}", "rule": "share", "version": version, "output": "share.value", "unit": "x",
            "valid_from": valid[0], "valid_until": valid[1], "known_from": known,
            "definitions": [{"name": "rated", "when": {"boolean": True},
                             "value": {"op": "add", "args": [rated, {"fact": "entry_total.total"}]}}]}


DEFINITION = [share("v1", ("2025-01-01", "2026-01-01"), "2024-12-01", "floor"),
              share("v2", ("2026-01-01", "2027-01-01"), "2025-12-01", "round")]


def write(at: Path, rel: str, doc: dict) -> None:
    (at / rel).parent.mkdir(parents=True, exist_ok=True)
    (at / rel).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")


def pin(at: Path, *dependencies: Path) -> None:
    doc = yaml.safe_load((at / "pack.yaml").read_text(encoding="utf-8"))
    doc["imports"] = [{"name": yaml.safe_load((d / "pack.yaml").read_text(encoding="utf-8"))["name"],
                       "path": "../" + d.name, "sha256": modules.pack_hash(d)} for d in dependencies]
    write(at, "pack.yaml", doc | {"name": at.name})


def definition_pack(at: Path, name: str, program: dict, theory: bool = False) -> Path:
    """A pack that holds the calculation itself: the kinds and rules it reads, and `program` as its calc file."""
    shutil.copytree(FIXTURE.parent / "calc", at)
    (at / "calc" / "example.yaml").unlink()
    write(at, "pack.yaml", {"name": name, "version": "0.1.0", "default_language": "nl", "theory": theory})
    write(at, "calc/share.yaml", dict(BINDINGS, pack=name) | program)
    return at


def consumer(at: Path, theory: Path, date: str | None, **program) -> Path:
    """A pack with kinds of its own that imports the theory and states the evaluation date in a calc file."""
    shutil.copytree(FIXTURE, at)
    pin(at, theory)
    if date is not None:
        write(at, "calc/date.yaml", {"format": "rezono.calc/1", "pack": at.name, "subject": "item",
                                     "as_of": {"valid_at": date, "known_at": date}} | program)
    return at


@pytest.fixture
def theory(tmp_path) -> Path:
    return definition_pack(tmp_path / "theory", THEORY, {"rules": DEFINITION}, theory=True)


def rows(prog: calc.Program, parameters: list[tuple], item: str = "item") -> dict[str, list[tuple]]:
    """The facts of an importing pack, with the evaluation date its program states. `item` is the engine
    name of the subject kind."""
    out = {item: [("i0",), ("i1",)], f"{item}__amount": [("i0", 7), ("i1", 250)],
           f"{item}__flag": [("i0", True), ("i1", False)],
           "entry": [("e0",), ("e1",)], "entry__item": [("e0", "i0"), ("e1", "i0")],
           "entry__name": [("e0", "x0"), ("e1", "y0")],
           "calc__as_of": [(a["id"], a["valid_at"], a["known_at"]) for a in calc_sql.rows(prog)["calc__as_of"]]}
    out |= {t: [] for t in ("setting", "setting__name", "setting__value", "setting__valid_from",
                            "setting__valid_until", "setting__known_from")}
    for e, name, v, valid_from, valid_until, known_from in parameters:
        out["setting"].append((e,))
        for slot, x in (("name", name), ("value", v), ("valid_from", valid_from), ("valid_until", valid_until),
                        ("known_from", known_from)):
            out[f"setting__{slot}"].append((e, x))
    return out


def outcome(at: Path, parameters: list[tuple], item: str = "item") -> tuple[dict, dict]:
    """(what DuckDB gives, the compiled calculation files) of a pack on its facts. The exact reference reads
    the program as written and must give the same, with the same witnesses (`run_both`)."""
    model = pack.read(at)
    prog = calc.build(model, model.calc)
    got, reference = run_both(model, prog, model.calc, rows(prog, parameters, item))
    assert got == reference
    files = emit.compile_pack(model)
    ir = json.loads(files["ir/calc.json"])
    return got, {f: files[f] for f in ("engine/calc.sql", "batch/calc.sql", "engine/calc.json")} | {"ir": ir | {"pack": ""}}


def test_the_theory_compiles_on_its_own_and_states_no_date(theory):
    model = pack.read(theory)
    assert model.meta["theory"] is True and "as_of" not in model.calc
    assert json.loads(emit.compile_pack(model)["engine/calc.json"]) == {"calc__as_of": []}


def test_each_consumer_gets_the_outcome_of_the_definition_written_in_one_pack(tmp_path, theory):
    """Two packs import one definition, each with its own evaluation date and parameter facts. Each gets what
    a pack gives that holds the same definition itself, to the byte of the compiled calculation; the exact
    reference agrees; and the two differ, since the date picks the version and the parameter row."""
    got = {}
    for name, (date, parameters) in CONSUMERS.items():
        importing = consumer(tmp_path / name, theory, date)
        single = definition_pack(tmp_path / f"single-{name}", "single",
                                 {"as_of": {"valid_at": date, "known_at": date}, "rules": DEFINITION})
        got[name], files = outcome(importing, parameters)
        assert (got[name], files) == outcome(single, parameters)
        assert pack.read(importing).calc["pack"] == name  # the program is the importing pack's
    # 7 at 15% is 1.05, rounded down, plus two entries; 7 at 50% is 3.5, rounded half away from zero, plus two.
    assert got["one"]["share"]["i0"] == ("known", "3", "", "rated", "v1")
    assert got["two"]["share"]["i0"] == ("known", "6", "", "rated", "v2")
    assert got["one"]["share"]["i1"][:2] == ("known", "37") and got["two"]["share"]["i1"][:2] == ("known", "125")


def test_an_imported_calculation_that_carries_a_date_is_refused(tmp_path):
    dated = definition_pack(tmp_path / "theory", THEORY, {"as_of": {"valid_at": "2026-06-01", "known_at": "2026-06-01"},
                                                         "rules": DEFINITION}, theory=True)
    pack.read(dated)  # on its own it is a pack with a date
    importing = consumer(tmp_path / "one", dated, "2025-06-01")
    with pytest.raises(CompileError, match=f"calc.import: {THEORY}:calc/share.yaml: an imported calculation carries no as_of"):
        pack.read(importing)


def test_a_consumer_that_states_no_date_for_an_imported_calculation_is_refused(tmp_path, theory):
    refusal = f"calc.import: {{}} imports the calculation of {THEORY} and states no evaluation date"
    with pytest.raises(CompileError, match=refusal.format("none")):
        pack.read(consumer(tmp_path / "none", theory, None))
    silent = consumer(tmp_path / "silent", theory, "2025-06-01")
    write(silent, "calc/date.yaml", {"format": "rezono.calc/1", "pack": "silent", "subject": "item"})
    with pytest.raises(CompileError, match=refusal.format("silent")):
        pack.read(silent)


def test_an_imported_calculation_is_pinned(tmp_path, theory):
    importing = consumer(tmp_path / "one", theory, "2025-06-01")
    write(theory, "calc/share.yaml", dict(BINDINGS, pack=THEORY, rules=DEFINITION[:1]))
    with pytest.raises(CompileError, match="the files hash to"):
        pack.read(importing)


TWICE = {"id": "twice@v1", "rule": "twice", "version": "v1", "output": "twice.value", "unit": "x",
         "valid_from": "2025-01-01", "valid_until": "2027-01-01", "known_from": "2024-12-01",
         "definitions": [{"name": "doubled", "when": {"boolean": True},
                          "value": {"op": "add", "args": [{"rule": "share"}, {"rule": "share"}]}}]}


def test_a_consumer_reads_an_imported_rule_and_adds_no_version_to_it(tmp_path, theory):
    date, parameters = CONSUMERS["two"]
    got, _ = outcome(consumer(tmp_path / "reads", theory, date, rules=[TWICE]), parameters)
    assert (got["share"]["i0"][:2], got["twice"]["i0"][:2]) == (("known", "6"), ("known", "12"))
    later = share("v3", ("2026-01-01", "2027-01-01"), "2026-01-01", "ceil")
    with pytest.raises(CompileError, match=f"calc.import: rule share belongs to pack {THEORY}: .*share@v3"):
        pack.read(consumer(tmp_path / "adds", theory, date, rules=[later]))


FINDINGS = '.decl high(item: symbol, value: number)\nhigh(x, v) :- calc__share(x, v, "known", ""), v > 5.\n'


def with_findings(at: Path, text: str = FINDINGS) -> Path:
    """The pack with a rule file that reads a selection of the calculation, beside the calculation."""
    (at / "rules" / "findings.dl").write_text(text, encoding="utf-8", newline="\n")
    return at


def test_a_rule_reads_the_selection_of_the_calculation_its_pack_brings(tmp_path):
    """A finding of the pack that holds the calculation, beside it, when another pack imports both.
    The rule IR is that of the same files in one pack, but for the module and the file it names; on the
    batch backend the rule reads the selection after the calculation (`batch.phases`), and given the rows
    of the selection it reads them as an input like a table."""
    from rezono_compiler import batch
    from rezono_compiler import rules as rule_ir

    theory = with_findings(definition_pack(tmp_path / "theory", THEORY, {"rules": DEFINITION}, theory=True))
    date, parameters = CONSUMERS["two"]
    importing = consumer(tmp_path / "two", theory, date)
    single = with_findings(definition_pack(tmp_path / "single", "single",
                                           {"as_of": {"valid_at": date, "known_at": date}, "rules": DEFINITION}))
    as_one = lambda at: dict(json.loads(json.dumps(pack.read(at).rules).replace("import_shared_calc_", "")  # noqa: E731
                                        .replace(f"{THEORY}:rules/", "rules/")), pack="")
    assert as_one(importing) == as_one(single)

    model = pack.read(importing)
    prog, calculation = rule_ir.load(model.rules), calc.build(model, model.calc)
    facts = {t: rs for t, rs in rows(calculation, parameters).items() if t != calc_sql.AS_OF}
    con, _, _ = batch.run(model, prog, facts, calculation)
    derived = batch.read(con, prog)
    assert derived["high"] == {("i0", "6"), ("i1", "125")}  # 7 at 50%, rounded, plus two entries; 250 at 50%
    selections = {n: sorted(rs) for n, rs in batch.read(con, prog, prog.calc_inputs()).items()}
    given = batch.connect(prog, scenarios.rule_rows(model, prog, facts) | selections)
    batch.compute(given, prog)
    assert batch.read(given, prog) == derived


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_the_rules_after_the_calculation_equal_souffle_with_the_selection_rows_as_input(tmp_path):
    """Bounded: one importing pack, two subjects. SoufflÃ© reads the rule files as written over the import
    closure, with the rows of the selection as an input, and gives as a set what the phases give."""
    import souffle
    from rezono_compiler import batch
    from rezono_compiler import rules as rule_ir

    theory = with_findings(definition_pack(tmp_path / "theory", THEORY, {"rules": DEFINITION}, theory=True))
    date, parameters = CONSUMERS["one"]
    importing = consumer(tmp_path / "one", theory, date)
    model = pack.read(importing)
    prog, calculation = rule_ir.load(model.rules), calc.build(model, model.calc)
    facts = {t: rs for t, rs in rows(calculation, parameters).items() if t != calc_sql.AS_OF}
    con, _, _ = batch.run(model, prog, facts, calculation)
    data =scenarios.rule_rows(model, prog, facts) | {n: sorted(rs) for n, rs in
                                                       batch.read(con, prog, prog.calc_inputs()).items()}
    assert data["calc__share"] and batch.read(con, prog)["high"]
    tmp = tmp_path / "souffle"
    tmp.mkdir()
    assert souffle.run(prog, data, tmp, program_text=souffle.pack_source(prog, importing)) == batch.read(con, prog)


def test_a_rule_of_an_imported_pack_on_the_importing_pack_s_selection_is_refused(tmp_path, monkeypatch):
    """The importing pack's own calculation rule is no selection the imported pack sees: refused, with the
    pack that gives it. And should the rules let it through, the calculation check still holds that the
    rule reads in its pack alone what it reads in the union."""
    from rezono_compiler import rules_dl

    theory = with_findings(definition_pack(tmp_path / "theory", THEORY, {"rules": DEFINITION}, theory=True),
                           '.decl high(item: symbol)\nhigh(x) :- calc__twice(x, v, "known", ""), v > 5.\n')
    date, _ = CONSUMERS["two"]
    importing = consumer(tmp_path / "reads", theory, date, rules=[TWICE])
    with pytest.raises(CompileError, match=f"{THEORY}:rules/findings.dl:2: calc__twice is a local calculation "
                                           "selection of reads"):
        pack.read(importing)
    read = rules_dl.read
    claimed = {THEORY: {"rules": [TWICE]}}  # as if the imported pack gave the importing pack's rule
    monkeypatch.setattr(rules_dl, "read", lambda *a, calc_parts=None, **k: read(*a, calc_parts=claimed, **k))
    with pytest.raises(CompileError, match=f"calc.import: a rule of pack {THEORY} reads calc__twice, which is no "
                                           "numeric selection of the calculation that pack sees"):
        pack.read(importing)


def test_a_calculation_comes_through_a_pack_between(tmp_path, theory):
    """A pack that imports the theory and adds a rule of its own, imported in turn: the program is the union
    over the closure, each pack once, and the pack between states no date. On its own it therefore does
    not compile; inside its importer it does."""
    between = Path(shutil.copytree(FIXTURE.parent / "shared", tmp_path / "between"))
    schema = between / "schema" / "terms.yaml"
    schema.write_text(schema.read_text(encoding="utf-8").replace("  - linkml:types\n", f"  - linkml:types\n  - {THEORY}:calc\n"),
                      encoding="utf-8", newline="\n")
    pin(between, theory)
    twice = dict(share("v1", ("2025-01-01", "2027-01-01"), "2024-12-01", "floor"), id="twice@v1", rule="twice")
    twice["definitions"][0]["value"] = {"op": "add", "args": [{"rule": "share"}, {"rule": "share"}]}
    write(between, "calc/twice.yaml", {"format": "rezono.calc/1", "pack": "between", "subject": "item", "rules": [twice]})
    with pytest.raises(CompileError, match=f"calc.import: between imports the calculation of {THEORY} and states no"):
        pack.read(between)
    date, parameters = CONSUMERS["two"]
    got, _ = outcome(consumer(tmp_path / "top", between, date), parameters)
    assert (got["share"]["i0"][:2], got["twice"]["i0"][:2]) == (("known", "6"), ("known", "12"))


def test_a_consumer_does_not_come_between_an_imported_calculation_and_what_it_reads(tmp_path):
    """In the theory `bonus.n` is an input concept. A relation `bonus` of the importing pack would make the
    same leaf read that relation: the definition would mean something else there."""
    inputs = {"kind": "entry", "subject": "item", "fact": "name", "integer": "number", "boolean": "truth"}
    reading = share("v1", ("2025-01-01", "2027-01-01"), "2024-12-01", "floor")
    reading["definitions"][0]["value"] = {"op": "add", "args": [{"fact": "item.amount"}, {"fact": "bonus.n"}]}
    theory = definition_pack(tmp_path / "theory", THEORY, {"inputs": inputs, "rules": [reading]}, theory=True)
    importing = consumer(tmp_path / "one", theory, "2025-06-01")
    pack.read(importing)
    (importing / "rules").mkdir()
    (importing / "rules" / "own.dl").write_text(".decl bonus(item: symbol, n: number)\nbonus(i, 1) :- item(i).\n",
                                                encoding="utf-8", newline="\n")
    with pytest.raises(CompileError, match=f"calc.import: fact bonus.n is a number input concept in pack {THEORY} "
                                           "and a number read from bonus in one"):
        pack.read(importing)
    # A rule whose type its own pack leaves open is a number there; a use that makes it a boolean changes it.
    reading["definitions"][0]["value"] = {"fact": "open"}
    write(theory, "calc/share.yaml", dict(BINDINGS, pack=THEORY, inputs=inputs, rules=[reading]))
    test = dict(share("v1", ("2025-01-01", "2027-01-01"), "2024-12-01", "floor"), id="test@v1", rule="test")
    test["definitions"][0]["value"] = {"op": "and", "args": [{"rule": "share"}, {"boolean": True}]}
    with pytest.raises(CompileError, match=f"calc.import: rule share is a number in pack {THEORY} and a boolean in typed"):
        pack.read(consumer(tmp_path / "typed", theory, "2025-06-01", rules=[test]))
    # And a binding the theory does not give is not the importing pack's to add where the theory reads through it.
    chosen = definition_pack(tmp_path / "plain", "plain", {"rules": DEFINITION}, theory=True)
    write(chosen, "calc/share.yaml", {k: v for k, v in dict(BINDINGS, pack="plain", rules=DEFINITION).items()
                                      if k != "parameter_choice"})
    with pytest.raises(CompileError, match="calc.import: parameter_choice of two differs from that of pack plain"):
        pack.read(consumer(tmp_path / "two", chosen, "2025-06-01", parameter_choice=CHOICE))


def test_an_imported_calculation_is_bound_to_the_names_of_the_importing_pack(tmp_path, theory):
    """The importing pack declares a kind with the name of the theory's subject, so both get their module as
    prefix. The imported program follows: it reads the theory's kind under its name there."""
    date, parameters = CONSUMERS["two"]
    importing = consumer(tmp_path / "two", theory, date)
    schema = importing / "schema" / "minimal.yaml"
    schema.write_text(schema.read_text(encoding="utf-8") + "  Item:\n    attributes:\n      id:\n        identifier: true\n",
                      encoding="utf-8", newline="\n")
    item = "shared_calc_calc_item"
    write(importing, "calc/date.yaml", {"format": "rezono.calc/1", "pack": "two", "subject": item,
                                        "as_of": {"valid_at": date, "known_at": date}})
    model = pack.read(importing)
    assert {"minimal_item", item} <= set(model.kinds) and "item" not in model.kinds
    assert model.calc["subject"] == item and calc.build(model, model.calc).facts[f"{item}.amount"].table == f"{item}__amount"
    got, _ = outcome(importing, parameters, item)
    assert got["share"]["i0"] == ("known", "6", "", "rated", "v2")


HASHED = ("pack.yaml", "channels.yaml", "schema/**/*.yaml", "rezono/**/*.rezono", "rezono/**/*.json",
          "labels/*.yaml", "messages/*.mf2", "rules/*.dl", "calc/*.yaml", "sweeps.yaml", "questions.yaml",
          "views.yaml", "icons/*.svg", "icons/sources.yaml")


def test_definition_hash_covers_each_file_family(tmp_path):
    """Independently construct the canonical path-to-digest map from known bytes."""
    paths = ("pack.yaml", "channels.yaml", "schema/nested/item.yaml", "rezono/nested/item.rezono",
             "rezono/nested/item.json", "labels/en.yaml", "messages/en.mf2", "rules/query.dl",
             "calc/total.yaml", "sweeps.yaml", "questions.yaml", "views.yaml", "icons/item.svg",
             "icons/sources.yaml")
    expected = {}
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        body = f"sample {path}\n".encode("ascii")
        target.write_bytes(body)
        expected[path] = hashlib.sha256(body).hexdigest()
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "data.yaml").write_bytes(b"item: []\n")
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode("ascii")
    assert modules.pack_hash(tmp_path) == hashlib.sha256(canonical).hexdigest()


@pytest.mark.xfail(strict=True, raises=FileNotFoundError,
                   reason="Document the definition-file families in docs/compiler/pack.md; see decisions/pack-hash-coverage.md.")
def test_hash_documentation_covers_every_definition_file_family():
    said = next(line for line in (REPO / "docs" / "compiler" / "pack.md").read_text(encoding="utf-8").splitlines()
                if line.startswith("- **The hash**"))
    assert [g for g in HASHED if f"`{g}`" not in said] == []


def test_the_definition_hash_of_every_pack_is_what_it_was():
    """Check every real pin, including a dependency that has a dependency of its own."""
    assert modules.DEFINITION == HASHED
    pins = [(meta.parent, i) for top in ("packs", "examples") for meta in sorted((REPO / top).rglob("pack.yaml"))
            if "expected" not in meta.parts
            for i in (yaml.safe_load(meta.read_text(encoding="utf-8")) or {}).get("imports") or []]
    assert pins, "no published pack exercises a real import pin"
    targets = {(at / pin["path"]).resolve() for at, pin in pins}
    assert any(at.resolve() in targets for at, _ in pins), "no imported pack is itself an importer"
    assert [f"{at.name}: {i['name']}" for at, i in pins if modules.pack_hash(at / i["path"]) != i["sha256"]] == []
