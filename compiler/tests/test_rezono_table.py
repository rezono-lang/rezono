"""Decision tables of modules written in Rezono (docs/rezono/publication.md §9.1): a derived value with
`table unique` lowers to a named outcome, the relation of its value and an invariant, as rules a rule file could
state. The rules are run on DuckDB for each state of an input; what this slice does not lower is refused at its
line. The modules are written as `rezono/` writes their form, with places laid out by hand (test_rezono_module).
Neutral names; no domain."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb
import pytest

import souffle
from support import FIXTURE, compile_dir
from test_rezono_module import add, module
from rezono_compiler import emit, pack, rezono_table, rules_sql
from rezono_compiler import rules as ir

LEVEL = {"enum": "Level", "world": "closed", "values": ["valid", "revoked", "suspended"]}
TONE = {"enum": "Tone", "world": "closed", "values": ["up", "down"]}
STANDING = {"enum": "Standing", "world": "closed", "values": ["good", "withdrawn"]}
BULK = {"enum": "Bulk", "world": "closed", "values": ["small", "large"]}
REASONS = "reason.no_value = {{Een waarde ontbreekt.}}\nreason.no_row_applies = {{Geen rij is van toepassing.}}\n"
ETA = {"kind": "Eta", "world": "closed", "slots": [{"slot": "level", "type": "Level"},
                                                    {"slot": "tone", "type": "Tone", "card": "?"}]}


def lit(v: str) -> dict:
    return {"lit": v}


def table(inputs: list[str], *rows, out: str = "standing", policy: str = "unique") -> dict:
    """A derived value `out` with a table: each row its cells (a list of tests, or "-") and its output last."""
    return {"derived": out, "type": out.capitalize() if out != "size_band" else "Bulk",
            "table": {"table": policy, "inputs": [{"path": [i]} for i in inputs], "output": out,
                      "rows": [{"tests": list(r[:-1]), "value": lit(r[-1])} for r in rows]}}


STANDING_TABLE = table(["level", "tone"],
                       ([lit("valid")], "-", "good"),
                       ([lit("revoked"), lit("suspended")], [lit("up")], "withdrawn"),
                       ([lit("suspended")], [lit("down")], "withdrawn"))
SIZE_TABLE = table(["size"], ([{"between": {"op": "..<", "to": lit("5")}}], "small"),
                   ([{"between": {"from": lit("5"), "op": ".."}}], "large"), out="size_band")


def written(tmp_path: Path, *decls) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    module(d, list(decls))
    # A named outcome asks the sentence of each reason it gives (publication.md §4, point 5).
    add(d / "messages" / "nl.mf2", REASONS)
    return d


def run(d: Path, rows: dict[str, list[tuple]]) -> duckdb.DuckDBPyConnection:
    """The pack's tables with `rows` in them, then its rules (batch, DuckDB)."""
    model = pack.read(d)
    db = duckdb.connect()
    db.execute(emit.tables(model))
    for t, rs in rows.items():
        db.executemany(f"INSERT INTO {emit.q(t)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    for statement in rules_sql.duckdb_program(ir.load(model.rules)):
        db.execute(statement)
    return db


def rows(db, relation: str) -> set[tuple]:
    return set(db.execute(f"SELECT * FROM {emit.q(relation)}").fetchall())


def test_unique_gives_one_state_for_every_element_in_each_state_of_its_inputs(tmp_path):
    d = written(tmp_path, LEVEL, TONE, STANDING, ETA | {"kind": "Eta"}, {"extend": "Eta", "derived": [STANDING_TABLE]})
    db = run(d, {"eta": [(e,) for e in ("e1", "e2", "e3", "e4", "e5", "e6")],
                 "eta__level": [("e1", "valid"), ("e2", "revoked"), ("e3", "revoked"), ("e6", "revoked")],
                 "eta__tone": [("e2", "up"), ("e4", "up"), ("e6", "down")]})
    assert rows(db, "eta_standing") == {
        ("e1", "known", ""),  # valid: the first row, whatever the tone
        ("e2", "known", ""),  # revoked and up: the second row
        ("e3", "unknown", "no_row_applies"),  # revoked, tone n/a: the cell is n/a, so no row applies (tables.md §3)
        ("e4", "unknown", "no_value"),  # level missing, tone up: rows 1 and 2 undecided, row 3 false
        ("e5", "unknown", "no_value"),  # both missing: n/a and unknown is unknown (Appendix A.1)
        ("e6", "unknown", "no_row_applies"),  # revoked and down: every row has a false cell
    }
    assert rows(db, "eta_standing_value") == {("e1", "good"), ("e2", "withdrawn")}
    assert rows(db, "eta_standing_conflict") == set()
    assert rows(db, "eta_standing_open") == {("e4", 1), ("e4", 2), ("e5", 1), ("e5", 2), ("e5", 3)}


def test_the_oracle_runs_the_text_the_compiler_reads(tmp_path):
    """The Soufflé program of the pack holds the table's rules, each relation declared once; with Soufflé at
    hand, it derives what DuckDB derives (the oracle of examples/test_rules.py sees a table as a rule file)."""
    d = written(tmp_path, LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [STANDING_TABLE]})
    prog = ir.load(pack.read(d).rules)
    text = souffle.pack_source(prog, d)
    declared = re.findall(r"^\s*\.decl\s+([a-z0-9_]+)", text, flags=re.M)
    assert "eta_standing" in declared and sorted(declared) == sorted(prog.relations)
    if shutil.which("souffle") is None:
        return
    data = {"eta": [(e,) for e in ("e1", "e2", "e3", "e4")], "eta__level": [("e1", "valid"), ("e2", "revoked")],
            "eta__tone": [("e2", "up"), ("e4", "down")]}
    db = run(d, data)
    oracle = souffle.run(prog, data, tmp_path, program_text=text)
    for name in ("eta_standing", "eta_standing_value", "eta_standing_conflict"):
        assert oracle[name] == {tuple(map(str, r)) for r in rows(db, name)}, name


def test_two_rows_that_apply_are_a_conflict_that_blocks(tmp_path):
    overlap = table(["level", "tone"], ([lit("valid")], "-", "good"), ("-", [lit("up")], "withdrawn"))
    d = written(tmp_path, LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [overlap]})
    model = pack.read(d)
    conflict = next(r for r in ir.load(model.rules).relations.values() if r.name == "eta_standing_conflict")
    assert conflict.invariant
    db = run(d, {"eta": [("e1",), ("e2",)], "eta__level": [("e1", "valid"), ("e2", "valid")],
                 "eta__tone": [("e1", "up"), ("e2", "down")]})
    assert rows(db, "eta_standing_conflict") == {("e1", 1, 2)}
    assert rows(db, "eta_standing") == {("e1", "known", ""), ("e2", "known", "")}


def test_a_whole_number_is_tested_by_range_and_an_optional_one_without_a_value_is_n_a(tmp_path):
    d = written(tmp_path, BULK, {"extend": "Alpha", "derived": [SIZE_TABLE]})
    db = run(d, {"alpha": [("a1",), ("a2",), ("a3",)], "alpha__title": [("a1", "x"), ("a2", "y"), ("a3", "z")],
                 "alpha__size": [("a1", 4), ("a2", 5)]})
    assert rows(db, "alpha_size_band") == {("a1", "known", ""), ("a2", "known", ""), ("a3", "unknown", "no_row_applies")}
    assert rows(db, "alpha_size_band_value") == {("a1", "small"), ("a2", "large")}


def test_the_rules_are_those_a_rule_file_would_state_at_the_lines_of_the_module(tmp_path):
    d = written(tmp_path, BULK, {"extend": "Alpha", "derived": [SIZE_TABLE]})
    model = pack.read(d)
    errors: list[str] = []
    [gen] = rezono_table.lower_pack(model, pack.read_meta(d), d, errors)
    assert errors == []
    assert gen.text == """\
// @outcome alpha
.decl alpha_size_band(alpha: symbol, state: symbol, reason: symbol)
.decl alpha_size_band_value(alpha: symbol, value: symbol)
.decl alpha_size_band_row(alpha: symbol, row: number)
.decl alpha_size_band_cell(alpha: symbol, row: number, column: number)
.decl alpha_size_band_applies(alpha: symbol)
// @invariant
.decl alpha_size_band_conflict(alpha: symbol, row: number, other: number)
alpha_size_band_cell(x, 1, 1) :- alpha__size(x, v), v < 5.
alpha_size_band_row(x, 1) :- alpha(x), alpha_size_band_cell(x, 1, 1).
alpha_size_band_value(x, "small") :- alpha_size_band_row(x, 1).
alpha_size_band_cell(x, 2, 1) :- alpha__size(x, v), v >= 5.
alpha_size_band_row(x, 2) :- alpha(x), alpha_size_band_cell(x, 2, 1).
alpha_size_band_value(x, "large") :- alpha_size_band_row(x, 2).
alpha_size_band_applies(x) :- alpha_size_band_row(x, _).
alpha_size_band_conflict(x, m, n) :- alpha_size_band_row(x, m), alpha_size_band_row(x, n), m < n.
alpha_size_band(x, "known", "") :- alpha_size_band_applies(x).
alpha_size_band(x, "unknown", "no_row_applies") :- alpha(x), !alpha_size_band_applies(x).
"""
    rules = ir.load(model.rules)
    outcome = rules.relations["alpha_size_band"]
    assert outcome.outcome == "alpha"
    # Each rule is the module's: its file, and the line of the derived value (the form places no row here).
    assert {(r.module, r.origin) for r in rules.rules.values() if r.head.relation.startswith("alpha_size_band")} == {
        ("m", ("rezono/m.rezono", 25))}
    # And the pack compiles as with a rule file: every engine, the bundle with the rule's place in the module.
    files = compile_dir(d, tmp_path / "out")
    spans = {r["relation"]: r["span"]["file"] for r in json.loads(files["bundle/schema-bundle.json"])["rules"]}
    assert spans["alpha_size_band"] == "rezono/m.rezono"
    assert '"alpha_size_band"' in files["engine/rules.sql"]


REFUSALS = {
    "total": ([LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [STANDING_TABLE | {"totality": "total"}]}],
              55, "`total` on a table is not lowered"),
    "a value without a table": ([{"extend": "Alpha", "derived": [{"derived": "ok", "type": "Bool",
                                                                   "value": lit("true")}]}],
                                15, "a derived value is not lowered yet"),
    "a kind the pack lacks": ([STANDING, {"extend": "Omega", "derived": [table(["x"], ([lit("1")], "good"))]}],
                              20, "Omega is not a kind of this pack"),
    "a path": ([STANDING, {"extend": "Beta", "derived": [{"derived": "standing", "type": "Standing", "table": {
        "table": "unique", "inputs": [{"path": ["alpha", "size"]}], "output": "standing",
        "rows": [{"tests": [[lit("1")]], "value": lit("good")}]}}]}],
               25, "an input is a slot of the kind in this slice"),
    "a text input": ([STANDING, {"extend": "Alpha", "derived": [table(["title"], ([lit("x")], "good"))]}],
                     25, "title is a string: an input is an enum or a whole number in this slice"),
    "an output that is no enum": ([{"extend": "Alpha", "derived": [table(["size"], ([lit("1")], "x"))
                                                                   | {"type": "Count"}]}],
                                  15, "standing is a Count: a table's output is an enum in this slice"),
    "a value outside the enum": ([LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [
        table(["level"], ([lit("expired")], "good"))]}], 55, "expired is not a value of level"),
    "a range over an enum": ([LEVEL, TONE, STANDING, ETA, {"extend": "Eta", "derived": [
        table(["level"], ([{"between": {"from": lit("valid"), "op": ".."}}], "good"))]}],
                             55, "a range needs an ordered type"),
}


@pytest.mark.parametrize("decls, line, message", REFUSALS.values(), ids=REFUSALS)
def test_what_the_slice_does_not_lower_is_refused_at_its_line(tmp_path, decls, line, message):
    d = written(tmp_path, *decls)
    with pytest.raises(pack.CompileError, match=re.escape(f"minimal/rezono/m.rezono:{line}: {message}")):
        pack.read(d)
