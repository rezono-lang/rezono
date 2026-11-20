"""The `@days(text, origin)` functor in the Soufflé test oracle helper (decisions/rule-day-numbers.md)."""

import re
import shutil
from datetime import date

import pytest

import souffle
from rezono_compiler import batch, rules, rules_dl


def _lower_decls(text: str) -> list[str]:
    return re.findall(r"^\s*\.decl\s+([a-z0-9_]+)", text, flags=re.M)


def _expected_days(text: str, origin: str = "1970-01-01") -> str:
    return str((date.fromisoformat(text) - date.fromisoformat(origin)).days)


ENDING_DL = """\
.decl derived_end(item: symbol, end_text: symbol)
derived_end(r, e) :- item_date(r, e).
.decl derived_day(item: symbol, day_num: number)
derived_day(r, d) :- derived_end(r, e), d = @days(e, "1970-01-01").
"""

ENDING_TABLES = {"item_date": [("id", "string"), ("value", "string")]}

WINDOW_DL = """\
.decl window_match(query: symbol, item: symbol, end_text: symbol)
window_match(q, item, end_text) :-
    window_query(q, as_of, horizon),
    horizon >= 0,
    catalog_entry(item, end_text),
    end_day = @days(end_text, "1970-01-01"),
    window_end = as_of + horizon,
    end_day >= as_of,
    end_day <= window_end.

.decl span_since_y2k(item: symbol, offset: number)
span_since_y2k(item, offset) :-
    catalog_entry(item, end_text),
    offset = @days(end_text, "2000-01-01").

.decl checked_instant(item: symbol, ts: symbol)
checked_instant(item, ts) :-
    item_stamp(item, ts),
    utc_instant(ts) = utc_instant(ts).
"""

WINDOW_TABLES = {
    "window_query": [("id", "string"), ("as_of", "integer"), ("horizon", "integer")],
    "catalog_entry": [("id", "string"), ("end_text", "string")],
    "item_stamp": [("id", "string"), ("ts", "string")],
}


def test_program_and_source_lower_days_functor_and_keep_declarations():
    doc = rules_dl.read_program(ENDING_DL, "days", ENDING_TABLES, "days_pack")
    prog = rules.load(doc)
    p_text = souffle.program(prog)
    s_text = souffle.source(prog, [ENDING_DL])

    for text in (p_text, s_text):
        assert "@days" not in text
        assert ".decl DayNum(x: symbol, n: number)" in text
        assert 'DayIn("1970-01-01").' in text
        assert "DayIn(x) :- item_date(_, x)." in text
        assert sorted(_lower_decls(text)) == sorted(prog.relations)
    assert 'DayNum(V_e, DayLeft_0_), DayNum("1970-01-01", DayRight_0_), V_d = DayLeft_0_ - DayRight_0_' in p_text
    assert 'DayNum(e, DayL_0_), DayNum("1970-01-01", DayR_0_), d = DayL_0_ - DayR_0_' in s_text

    # Comments stay untouched; multi-line spacing and multiple `@days` calls in one rule get distinct temps.
    multi_dl = """\
// comment keeping d = @days(e, "1970-01-01") untouched
.decl delta(item: symbol, diff: number)
delta(r, diff) :-
    item_date(r, a),
    item_date(r, b),
    da = @days( a ,
        "1970-01-01" ),
    db = @days(b, "2000-01-01"),
    diff = da - db.
"""
    rewritten = souffle.source(prog, [multi_dl])
    assert '// comment keeping d = @days(e, "1970-01-01") untouched' in rewritten
    code_only = "\n".join(line for line in rewritten.splitlines() if not line.lstrip().startswith("//"))
    assert "@days" not in code_only
    assert 'DayNum(a, DayL_0_), DayNum("1970-01-01", DayR_0_), da = DayL_0_ - DayR_0_' in code_only
    assert 'DayNum(b, DayL_1_), DayNum("2000-01-01", DayR_1_), db = DayL_1_ - DayR_1_' in code_only
    assert 'DayIn("1970-01-01").' in code_only and 'DayIn("2000-01-01").' in code_only


def test_bound_preserves_days_functor_name():
    written = 'ending_day(r, d) :- entry__end(r, e), d = @days(e, "1970-01-01").'
    got = souffle.bound(written, {"entry": "shared_entry", "days": "shared_days"})
    assert got == 'ending_day(r, d) :- shared_entry__end(r, e), d = @days(e, "1970-01-01").'


def test_plain_program_and_source_omit_day_helpers():
    raw = ".decl seen(x: symbol)\nseen(x) :- item(x).\n"
    doc = rules_dl.read_program(raw, "plain", {"item": [("id", "string")]}, "plain")
    prog = rules.load(doc)
    for text in (souffle.program(prog), souffle.source(prog, [raw])):
        assert "DayNum" not in text
        assert "DayIn" not in text


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_program_and_source_compute_day_numbers_and_reject_invalid_dates(tmp_path):
    doc = rules_dl.read_program(ENDING_DL, "days", ENDING_TABLES, "days_pack")
    prog = rules.load(doc)
    valid = {
        "first": "0001-01-01",
        "c1900_feb28": "1900-02-28",
        "c1900_mar01": "1900-03-01",
        "before_epoch": "1969-12-31",
        "epoch": "1970-01-01",
        "leap_400": "2000-02-29",
        "leap_4": "2024-02-29",
        "after_leap": "2024-03-01",
        "last": "9999-12-31",
    }
    invalid = {
        "year_zero": "0000-01-01",
        "year_zero_end": "0000-12-31",
        "non_leap_1900": "1900-02-29",
        "non_leap_2023": "2023-02-29",
        "feb_30": "2026-02-30",
        "apr_31": "2024-04-31",
        "month_00": "2024-00-10",
        "month_13": "2024-13-01",
        "day_00": "2024-01-00",
        "short_year": "26-02-01",
        "word": "soon",
        "empty": "",
    }
    data = {"item_date": [(k, v) for k, v in (valid | invalid).items()]}
    want = {(k, _expected_days(v)) for k, v in valid.items()}

    with batch.connect(prog, data) as con:
        batch.compute(con, prog)
        derived = batch.read(con, prog)
    assert derived["derived_day"] == want
    assert souffle.run(prog, data, tmp_path) == derived
    src = souffle.source(prog, [ENDING_DL])
    assert souffle.run(prog, data, tmp_path, program_text=src) == derived


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_inclusive_date_window_custom_origin_and_utc_coexistence(tmp_path):
    doc = rules_dl.read_program(WINDOW_DL, "window", WINDOW_TABLES, "window_pack")
    prog = rules.load(doc)
    as_of = int(_expected_days("2026-03-01"))
    data = {
        "window_query": [("q1", as_of, 30), ("q_neg", as_of, -1)],
        "catalog_entry": [
            ("before", "2026-02-28"),
            ("on_start", "2026-03-01"),
            ("inside", "2026-03-15"),
            ("on_end", "2026-03-31"),
            ("after", "2026-04-01"),
            ("malformed", "2026-02-30"),
        ],
        "item_stamp": [
            ("ok", "2026-03-01T00:00:00Z"),
            ("bad", "2023-02-29T12:00:00Z"),
        ],
    }
    with batch.connect(prog, data) as con:
        batch.compute(con, prog)
        derived = batch.read(con, prog)

    assert derived["window_match"] == {
        ("q1", "on_start", "2026-03-01"),
        ("q1", "inside", "2026-03-15"),
        ("q1", "on_end", "2026-03-31"),
    }
    assert derived["span_since_y2k"] == {
        (k, _expected_days(d, "2000-01-01"))
        for k, d in data["catalog_entry"] if k != "malformed"
    }
    assert derived["checked_instant"] == {("ok", "2026-03-01T00:00:00Z")}

    assert souffle.run(prog, data, tmp_path) == derived
    src = souffle.source(prog, [WINDOW_DL])
    assert souffle.run(prog, data, tmp_path, program_text=src) == derived
