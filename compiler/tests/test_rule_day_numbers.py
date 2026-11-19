"""A rule reads an ISO date text as a day number, from decisions/rule-day-numbers.md.

The date here is a derived text, as a rule over a published support end date sees it. A view cannot reach it,
because a view reads base slots only. The expected day numbers come from Python's calendar, independently of
the engine.
"""

import json
import shutil
from contextlib import closing
from datetime import date

import pytest
import yaml
from rezono_compiler import batch, emit, facts, pack, rules, rules_sql
from support import FIXTURE

SOURCE = """
.decl ending(record: symbol, end: symbol)
ending(r, e) :- alpha__title(r, e).
.decl ending_day(record: symbol, day: number)
ending_day(r, d) :- ending(r, e), d = @days(e, "1970-01-01").
"""
TITLES = {"leap": "2024-02-29", "next": "2024-03-01", "epoch": "1970-01-01", "before": "1969-12-31",
          "no-day": "2026-02-30", "short": "26-02-01", "word": "soon"}


def day(text):
    return (date.fromisoformat(text) - date(1970, 1, 1)).days


def test_rules_read_a_text_date_as_a_day_number(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    (folder / "rules").mkdir()
    source = folder / "rules/days.dl"
    source.write_text(SOURCE, encoding="utf-8")
    model = pack.read(folder)

    program = rules.load(json.loads(emit.compile_pack(model)["ir/rules.json"]))
    alpha = yaml.safe_load((folder / "schema/minimal.yaml").read_bytes())["classes"]["Alpha"]["attributes"]
    data = {"alpha": [{"id": key, **{name: f"{key}-{name}" for name, slot in alpha.items()
                                      if name != "id" and isinstance(slot, dict) and slot.get("required")},
                       "title": text} for key, text in TITLES.items()]}
    with closing(batch.connect(program, facts.rows_of(model, data))) as db:
        batch.compute(db, program, witnesses=True)
        derived = batch.read(db, program)
    # A text that is no calendar day derives nothing; every real day gets its proleptic Gregorian number,
    # read back as canonical decimal text.
    assert set(derived["ending_day"]) == {(key, str(day(TITLES[key]))) for key in ("leap", "next", "epoch", "before")}
    assert day("2024-03-01") - day("2024-02-29") == 1  # control on the oracle itself

    # The origin is a constant ISO date, and the operand a bound text variable.
    for wrong in ('d = @days(e, r)', 'd = @days(e, "1970-1-1")', 'd = @days(20240229, "1970-01-01")'):
        source.write_text(SOURCE.replace('d = @days(e, "1970-01-01")', wrong), encoding="utf-8")
        with pytest.raises(pack.CompileError):
            pack.read(folder)


def test_year_zero_is_no_day_for_the_engine_as_for_the_checker(tmp_path):
    """Review round 7 (#718): DuckDB cast '0000-01-01' to a day, while the checker's `_days` gives None, so a
    publication was refused. Both SQL dialects now require a year Y >= 1, as Python's calendar does."""
    from rezono_checker.evaluate import _days

    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    (folder / "rules").mkdir()
    (folder / "rules/days.dl").write_text(SOURCE, encoding="utf-8")
    model = pack.read(folder)
    program = rules.load(json.loads(emit.compile_pack(model)["ir/rules.json"]))
    alpha = yaml.safe_load((folder / "schema/minimal.yaml").read_bytes())["classes"]["Alpha"]["attributes"]
    titles = {"zero": "0000-01-01", "zero-end": "0000-12-31", "first": "0001-01-01", "leap": "2024-02-29"}
    data = {"alpha": [{"id": key, **{name: f"{key}-{name}" for name, slot in alpha.items()
                                      if name != "id" and isinstance(slot, dict) and slot.get("required")},
                       "title": text} for key, text in titles.items()]}
    with closing(batch.connect(program, facts.rows_of(model, data))) as db:
        batch.compute(db, program, witnesses=True)
        derived = batch.read(db, program)
    checker = {(key, _days(text, "1970-01-01")) for key, text in titles.items()}
    assert set(derived["ending_day"]) == {row for row in checker if row[1] is not None}
    assert {key for key, value in checker if value is None} == {"zero", "zero-end"}
    assert ("first", str(day("0001-01-01"))) in derived["ending_day"]

    # Feldera gets the same guard; its live run is in the Feldera queue.
    sql = rules_sql.feldera(program)
    assert "RLIKE" in sql and ">= '0001'" in sql
