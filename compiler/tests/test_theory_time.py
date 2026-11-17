"""Theory std-time (#314 §5.2, T4; lane G, G03; rulings RV-C13 and RV-C18): its axioms and rules against independent oracles.

Three evaluations must agree as sets: an exact Python reference written from the definitions (bounds per
interval and a decision tree for Allen's relations, not the thirteen rules), the DuckDB batch backend on the
compiled IR, and Soufflé on rules/time.dl as written (when present, as in CI). The must-fail cases show that
each axiom fires. No domain: intervals are letters, positions are whole numbers; the validity cases of Reckon
§5a are read as positions by this test, not by the theory.

A bound has three states (RV-C13): stated, stated to be absent, or not recorded. What nobody recorded is
unknown: the judgement says so with a reason, and no row says the interval holds, has begun or has ended.
The judgement reads how the interval stands, and a tone that reassures stands exactly where it holds; a
knowledge time nobody recorded is unknown too (RV-C18).
"""

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from rezono_compiler import emit, pack
from rezono_compiler import rules as ir

THEORY = Path(__file__).resolve().parents[2] / "packs" / "std-time"
pytest.importorskip("duckdb")

INVERSE = {"before": "after", "meets": "met_by", "overlaps": "overlapped_by", "starts": "started_by",
           "during": "contains", "finishes": "finished_by", "equals": "equals"}
INVERSE |= {v: k for k, v in INVERSE.items()}
REASONS = {"end_beyond_horizon": "positive", "end_within_horizon": "attention", "in_extension": "attention",
           "ended": "negative", "extension_ended": "negative", "without_end": "no_end", "end_not_recorded": "unknown",
           "start_ahead": "not_begun", "start_not_recorded": "unknown"}
REASSURING = {("positive", "end_beyond_horizon"), ("attention", "end_within_horizon"), ("no_end", "without_end")}
JUDGEMENTS = set(REASONS.values())
AXIOMS = ["bound_contradicted", "extension_inverted", "extension_without_end", "interval_inverted", "series_across_axes"]
ABSENCES = ["end_not_recorded", "known_from_not_recorded", "start_not_recorded"]
DERIVED = sorted(AXIOMS + ABSENCES + ["allen", "begun_at", "ended_at", "end_stated", "extension_stated",
                                      "known_from_stated", "start_stated", "holds_at", "in_extension", "judgement",
                                      "known_at", "span"])


@dataclass(frozen=True)
class Interval:
    """One interval as a domain would state it. None is a bound that has no row. `no_start` and `no_end` are the
    statement that the interval has no such bound; a bound with neither a row nor that statement is unknown."""
    line: str
    start: int | None = None
    end: int | None = None
    extension_end: int | None = None
    known_from: int | None = None
    series: str | None = None
    no_start: bool = False
    no_end: bool = False


def tables(intervals, references):
    """The theory's base tables for a world: intervals by id, references as id -> (line, position, horizon)."""
    slot = lambda name: sorted((i, getattr(v, name)) for i, v in intervals.items() if getattr(v, name) is not None)  # noqa: E731
    return {
        "interval__on_axis": slot("line"), "interval__start": slot("start"), "interval__end": slot("end"),
        "interval__extension_end": slot("extension_end"), "interval__known_from": slot("known_from"),
        "interval__in_series": slot("series"),
        "interval__unbounded": sorted([(i, "start") for i, v in intervals.items() if v.no_start]
                                      + [(i, "end") for i, v in intervals.items() if v.no_end]),
        "reference_point__on_axis": sorted((r, v[0]) for r, v in references.items()),
        "reference_point__position": sorted((r, v[1]) for r, v in references.items()),
        "reference_point__horizon": sorted((r, v[2]) for r, v in references.items()),
    }


def allen_relation(s, e, t, f):
    """Allen's relation of [s, e) to [t, f), as a decision tree over the four bounds."""
    if e <= t:
        return "before" if e < t else "meets"
    if f <= s:
        return "after" if f < s else "met_by"
    if s == t:
        return "equals" if e == f else "starts" if e < f else "started_by"
    if e == f:
        return "finishes" if s > t else "finished_by"
    if t < s and e < f:
        return "during"
    if s < t and f < e:
        return "contains"
    return "overlaps" if s < t else "overlapped_by"


def reference(intervals, references):
    """The definitions of the README, read per interval. A half-open interval covers start <= p < end. A bound
    counts only when it is stated or stated to be absent. The judgement is the README's table, row by row, each
    row with its condition written out (no "else"): `ordered` below is the same table as a decision tree, and
    the property test holds the two equal wherever no bound is contradicted."""
    out = {name: set() for name in DERIVED}
    for i, v in intervals.items():
        s, e, x = v.start, v.end, v.extension_end
        start_unknown, end_unknown = s is None and not v.no_start, e is None and not v.no_end
        if s is not None:
            out["start_stated"].add((i,))
        if e is not None:
            out["end_stated"].add((i,))
        if x is not None:
            out["extension_stated"].add((i,))
        if v.known_from is not None:
            out["known_from_stated"].add((i,))
        else:
            out["known_from_not_recorded"].add((i,))
        if start_unknown:
            out["start_not_recorded"].add((i,))
        if end_unknown:
            out["end_not_recorded"].add((i,))
        if s is not None and e is not None and not s < e:
            out["interval_inverted"].add((i,))
        if (s is not None and v.no_start) or (e is not None and v.no_end):
            out["bound_contradicted"].add((i,))
        if e is not None and x is not None and x < e:
            out["extension_inverted"].add((i,))
        if x is not None and (end_unknown or v.no_end):
            out["extension_without_end"].add((i,))
        for r, (line, p, h) in references.items():
            if line != v.line:
                continue   # positions on different lines are never compared
            begun_at = v.no_start or (s is not None and s <= p)
            ended_at = e is not None and e <= p
            extended = ended_at and x is not None and p < x
            if begun_at:
                out["begun_at"].add((i, r))
            if ended_at:
                out["ended_at"].add((i, r))
            if begun_at and (v.no_end or (e is not None and p < e)):
                out["holds_at"].add((i, r))
            if extended:
                out["in_extension"].add((i, r))
            if v.known_from is not None and v.known_from <= p:
                out["known_at"].add((i, r))
            ahead = s is not None and p < s                          # a stated start lies ahead
            goes_on = v.no_end or (e is not None and p < e)          # the end is known not to have come
            reasons = set()
            if ended_at:
                reasons.add("in_extension" if extended else "ended" if x is None else "extension_ended")
            if ahead and (goes_on or end_unknown):
                reasons.add("start_ahead")
            if end_unknown and (begun_at or start_unknown):
                reasons.add("end_not_recorded")
            if start_unknown and goes_on:
                reasons.add("start_not_recorded")
            if begun_at and goes_on:                                 # it holds
                if v.no_end:
                    reasons.add("without_end")
                if e is not None and p < e:
                    reasons.add("end_within_horizon" if e <= p + h else "end_beyond_horizon")
            out["judgement"] |= {(i, r, REASONS[reason], reason) for reason in reasons}
    spans = {i: (v.series, v.start, v.end) for i, v in intervals.items()
             if v.series is not None and v.start is not None and v.end is not None and v.start < v.end}
    out["span"] = {(i, q, s, e) for i, (q, s, e) in spans.items()}
    for a, (q, s, e) in spans.items():
        for b, (q2, t, f) in spans.items():
            if a != b and q == q2:
                out["allen"].add((a, b, allen_relation(s, e, t, f)))
    lines = {}
    for v in intervals.values():
        if v.series is not None:
            lines.setdefault(v.series, set()).add(v.line)
    out["series_across_axes"] = {(q,) for q, on in lines.items() if len(on) > 1}
    return out


def ordered(v, p, h):
    """RV-C18 point 1 as a decision tree, for an interval no bound of which is contradicted: the first case that
    applies decides, so there is exactly one answer."""
    s, e, x = v.start, v.end, v.extension_end
    if e is not None and e <= p:                                         # 1. the end has come
        if x is None:
            return "negative", "ended"
        return ("attention", "in_extension") if p < x else ("negative", "extension_ended")
    if s is not None and p < s:                                          # 2. the start lies ahead
        return "not_begun", "start_ahead"
    if e is None and not v.no_end:                                       # 3. nobody recorded the end
        return "unknown", "end_not_recorded"
    if s is None and not v.no_start:                                     # 4. nobody recorded the start
        return "unknown", "start_not_recorded"
    if v.no_end:                                                         # 5. it holds; the end decides
        return "no_end", "without_end"
    return ("attention", "end_within_horizon") if e <= p + h else ("positive", "end_beyond_horizon")


def program():
    return ir.load(pack.read(THEORY).rules)


def batch_eval(prog, data):
    from rezono_compiler import batch
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    return batch.read(con, prog)


def as_text(result):
    return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in result.items()}


def evaluate(intervals, references, tmp_path):
    """Every engine at hand, each compared with the reference."""
    prog, data = program(), tables(intervals, references)
    want = as_text(reference(intervals, references))
    assert as_text(batch_eval(prog, data)) == want
    if shutil.which("souffle"):
        import souffle
        text = souffle.source(prog, [p.read_text("utf-8") for p in sorted((THEORY / "rules").glob("*.dl"))])
        assert souffle.run(prog, data, tmp_path, program_text=text) == want
    return want


def test_the_theory_is_fact_free_and_compiles_on_its_own():
    theory = pack.read(THEORY)
    assert theory.meta["theory"] is True and not (THEORY / "facts").exists()
    assert set(theory.kinds) == {"interval", "axis", "series", "reference_point"}   # within the size limit of #314 §4
    files = emit.compile_pack(theory)
    for table in ("interval__start", "interval__end", "interval__unbounded", "interval__on_axis",
                  "reference_point__position"):
        assert f'"{table}"' in files["engine/tables.sql"]
    prog = program()
    assert sorted(r.name for r in prog.relations.values() if r.role == "derived") == DERIVED
    assert sorted(r.name for r in prog.relations.values() if getattr(r, "invariant", False)) == AXIOMS
    assert sorted(r.name for r in prog.relations.values() if getattr(r, "absence", False)) == ABSENCES
    assert [q["term"] for q in theory.questions] == ["time_grounds", "time_reach"]
    # The values the rules write are the values the schema names, so a label exists for each.
    assert set(theory.enums["interval_relation"]) == set(INVERSE)
    assert set(theory.enums["judgement_value"]) == JUDGEMENTS
    assert set(theory.enums["judgement_reason"]) == set(REASONS)
    assert set(theory.enums["bound_side"]) == {"start", "end"}


def test_a_bound_is_open_so_a_missing_row_is_unknown_to_the_compiler():
    """W6: start and end are open, and so is every relation that reads one. A rule of a domain that negates
    such a relation ("it has not ended") does not compile: an end nobody recorded cannot be read as "no end".
    The two relations about the registration are closed, as is the statement that a bound is absent."""
    world = {r.name: getattr(r, "world", "closed") for r in program().relations.values()}
    for name in ("interval__start", "interval__end", "interval__known_from", "begun_at", "ended_at", "holds_at",
                 "in_extension", "known_at", "judgement"):
        assert world[name] == "open", name
    for name in ("interval__unbounded", "interval__extension_end", "start_not_recorded", "end_not_recorded",
                 "known_from_not_recorded"):
        assert world[name] == "closed", name


def test_an_interval_is_half_open(tmp_path):
    world = {"a": Interval("days", 10, 20)}
    refs = {f"r{p}": ("days", p, 0) for p in (9, 10, 19, 20)}
    got = evaluate(world, refs, tmp_path)
    assert got["holds_at"] == {("a", "r10"), ("a", "r19")}      # the start is covered, the end is not
    assert got["begun_at"] == {("a", "r10"), ("a", "r19"), ("a", "r20")}
    assert got["ended_at"] == {("a", "r20")}


def test_a_bound_that_is_stated_to_be_absent_bounds_nothing_and_is_never_a_number(tmp_path):
    world = {"no_end": Interval("days", start=10, no_end=True), "no_start": Interval("days", end=10, no_start=True),
             "unbounded": Interval("days", no_start=True, no_end=True)}
    got = evaluate(world, {"early": ("days", -1000, 5), "late": ("days", 1000, 5)}, tmp_path)
    assert got["holds_at"] == {("no_end", "late"), ("no_start", "early"),
                               ("unbounded", "early"), ("unbounded", "late")}
    assert got["end_stated"] == {("no_start",)} and got["start_stated"] == {("no_end",)}
    assert not got["start_not_recorded"] and not got["end_not_recorded"]
    # No end: while it holds the judgement says so; it is neither positive nor negative. Before its start it
    # has not begun (RV-C18).
    assert {(i, r, v, why) for i, r, v, why in got["judgement"] if i != "no_start"} == {
        ("no_end", "early", "not_begun", "start_ahead"), ("no_end", "late", "no_end", "without_end"),
        ("unbounded", "early", "no_end", "without_end"), ("unbounded", "late", "no_end", "without_end")}
    assert got["span"] == set()


def test_an_end_nobody_recorded_is_unknown_never_positive(tmp_path):
    """RV-C13, on the README's reading A: a version's support window. The end of support of `silent` is not
    published, and nobody said that support never ends. At every reference the judgement is unknown with the
    reason, and no row says that support holds or that it has ended. `perpetual` is the contrast: the vendor
    states that support does not end."""
    world = {"silent": Interval("days", start=100), "dated": Interval("days", start=100, end=500),
             "perpetual": Interval("days", start=100, no_end=True)}
    refs = {"before": ("days", 50, 90), "soon": ("days", 150, 90), "late": ("days", 100000, 90)}
    got = evaluate(world, refs, tmp_path)
    assert got["end_not_recorded"] == {("silent",)}
    assert {(r, v, why) for i, r, v, why in got["judgement"] if i == "silent"} == {
        ("before", "not_begun", "start_ahead"),                  # its stated start lies ahead (RV-C18)
        ("soon", "unknown", "end_not_recorded"), ("late", "unknown", "end_not_recorded")}
    assert not {r for i, r in got["holds_at"] | got["ended_at"] if i == "silent"}
    assert {r for i, r in got["begun_at"] if i == "silent"} == {"soon", "late"}        # the start is stated
    assert {r for i, r in got["holds_at"] if i == "perpetual"} == {"soon", "late"}
    assert {r for i, r in got["holds_at"] if i == "dated"} == {"soon"}


def test_a_start_nobody_recorded_is_unknown_too(tmp_path):
    world = {"a": Interval("days", end=20), "b": Interval("days")}
    got = evaluate(world, {"in": ("days", 10, 0), "out": ("days", 30, 0)}, tmp_path)
    assert got["start_not_recorded"] == {("a",), ("b",)} and got["end_not_recorded"] == {("b",)}
    assert not got["begun_at"] and not got["holds_at"]           # nothing says it has begun, so nothing says it holds
    assert got["ended_at"] == {("a", "out")}                     # a stated end that has come has come
    # RV-C18: the end of a lies ahead at `in`, yet nobody recorded its start, so it is not positive.
    assert got["judgement"] == {
        ("a", "in", "unknown", "start_not_recorded"), ("a", "out", "negative", "ended"),
        ("b", "in", "unknown", "end_not_recorded"), ("b", "out", "unknown", "end_not_recorded")}


def test_a_start_ahead_has_not_begun_whatever_the_end(tmp_path):
    """RV-C18: an interval whose stated start lies ahead of the reference has not begun. That is known, so the
    value is not_begun, never positive and never unknown, whatever is or is not recorded of its end."""
    world = {"dated": Interval("days", 50, 500), "open": Interval("days", 50, no_end=True),
             "silent": Interval("days", 50), "near": Interval("days", 50, 60)}
    got = evaluate(world, {"r": ("days", 10, 90)}, tmp_path)
    assert got["judgement"] == {(i, "r", "not_begun", "start_ahead") for i in world}
    assert not got["holds_at"] and not got["begun_at"]


def test_reading_a_a_version_whose_release_nobody_recorded_is_unknown(tmp_path):
    """RV-C18 on the README's reading A, a version's support window. `unreleased` is announced for day 300 and
    has not begun at day 100; `unrecorded` has an end of support far ahead and nobody recorded its release,
    so whether it is supported is unknown; `supported` is the contrast."""
    world = {"unreleased": Interval("days", 300, 900), "unrecorded": Interval("days", end=900),
             "supported": Interval("days", 50, 900)}
    got = evaluate(world, {"today": ("days", 100, 90)}, tmp_path)
    assert got["judgement"] == {("unreleased", "today", "not_begun", "start_ahead"),
                                ("unrecorded", "today", "unknown", "start_not_recorded"),
                                ("supported", "today", "positive", "end_beyond_horizon")}
    assert got["holds_at"] == {("supported", "today")}


def test_positions_on_different_lines_are_never_compared(tmp_path):
    world = {"a": Interval("days", 1, 5), "b": Interval("stages", 1, 5)}
    got = evaluate(world, {"r": ("stages", 3, 0)}, tmp_path)
    assert got["holds_at"] == {("b", "r")} and {i for i, *_ in got["judgement"]} == {"b"}


def test_the_judgement_reads_the_end_the_extension_and_the_horizon(tmp_path):
    world = {"far": Interval("days", 0, 200), "near": Interval("days", 0, 130), "edge": Interval("days", 0, 190),
             "past": Interval("days", 0, 100), "extended": Interval("days", 0, 100, extension_end=150),
             "lapsed": Interval("days", 0, 50, extension_end=100), "open": Interval("days", 0, no_end=True),
             "silent": Interval("days", 0)}
    got = evaluate(world, {"r": ("days", 100, 90)}, tmp_path)
    assert got["judgement"] == {
        ("far", "r", "positive", "end_beyond_horizon"),
        ("near", "r", "attention", "end_within_horizon"),
        ("edge", "r", "attention", "end_within_horizon"),            # 190 = 100 + 90: near
        ("past", "r", "negative", "ended"),                          # the end is the first position not covered
        ("extended", "r", "attention", "in_extension"),              # one tone as `near`, another reason
        ("lapsed", "r", "negative", "extension_ended"),
        ("open", "r", "no_end", "without_end"), ("silent", "r", "unknown", "end_not_recorded")}
    assert got["in_extension"] == {("extended", "r")}
    # A horizon of zero: nothing ahead counts as near.
    assert evaluate({"near": Interval("days", 0, 101)}, {"r": ("days", 100, 0)}, tmp_path)["judgement"] == {
        ("near", "r", "positive", "end_beyond_horizon")}


def test_knowledge_is_apart_from_what_the_interval_covers(tmp_path):
    world = {"a": Interval("days", 100, 200, known_from=150), "b": Interval("days", 100, 200, known_from=130)}
    got = evaluate(world, {"valid": ("days", 120, 0), "cut": ("days", 140, 0)}, tmp_path)
    assert {i for i, r in got["holds_at"] if r == "valid"} == {"a", "b"}
    assert {i for i, r in got["known_at"] if r == "cut"} == {"b"}      # a holds at 120 and was not known at 140


def test_a_knowledge_time_nobody_recorded_is_unknown_never_always_known(tmp_path):
    """RV-C18 point 2: an interval without known_from has no known_at row at any reference, however late, and
    the absence relation names it. It still holds where its bounds say so: knowledge is apart from that."""
    world = {"silent": Interval("days", 100, 200), "stated": Interval("days", 100, 200, known_from=90)}
    refs = {"early": ("days", -1000, 0), "valid": ("days", 150, 0), "late": ("days", 10**6, 0)}
    got = evaluate(world, refs, tmp_path)
    assert got["known_at"] == {("stated", "valid"), ("stated", "late")}
    assert got["known_from_not_recorded"] == {("silent",)} and got["known_from_stated"] == {("stated",)}
    assert {i for i, r in got["holds_at"] if r == "valid"} == {"silent", "stated"}


ALLEN_CASES = {  # b is [10, 20); each a is in Allen's relation to it
    "before": (1, 5), "meets": (5, 10), "overlaps": (5, 15), "starts": (10, 15), "during": (12, 18),
    "finishes": (15, 20), "equals": (10, 20), "after": (25, 30), "met_by": (20, 25),
    "overlapped_by": (15, 25), "started_by": (10, 25), "contains": (5, 25), "finished_by": (5, 20)}


def test_allen_gives_each_of_the_thirteen_relations(tmp_path):
    for name, (s, e) in ALLEN_CASES.items():
        got = evaluate({"a": Interval("days", s, e, series="q"), "b": Interval("days", 10, 20, series="q")}, {}, tmp_path)
        assert got["allen"] == {("a", "b", name), ("b", "a", INVERSE[name])}, name


def test_allen_relates_only_proper_spans_of_one_series(tmp_path):
    world = {"a": Interval("days", 1, 5, series="q"), "b": Interval("days", 5, 9, series="q"),
             "other": Interval("days", 1, 5, series="p"), "loose": Interval("days", 1, 5),
             "open": Interval("days", 1, series="q")}
    got = evaluate(world, {}, tmp_path)
    assert got["allen"] == {("a", "b", "meets"), ("b", "a", "met_by")}
    assert {i for i, *_ in got["span"]} == {"a", "b", "other"}


@pytest.mark.parametrize("world, axiom, rows", [
    ({"a": Interval("days", 5, 5)}, "interval_inverted", {("a",)}),                    # empty: start = end
    ({"a": Interval("days", 9, 2)}, "interval_inverted", {("a",)}),
    ({"a": Interval("days", 1, 9, extension_end=8)}, "extension_inverted", {("a",)}),
    ({"a": Interval("days", 1, extension_end=8)}, "extension_without_end", {("a",)}),
    ({"a": Interval("days", 1, extension_end=8, no_end=True)}, "extension_without_end", {("a",)}),
    ({"a": Interval("days", 1, 9, no_start=True)}, "bound_contradicted", {("a",)}),
    ({"a": Interval("days", 1, 9, no_end=True)}, "bound_contradicted", {("a",)}),
    ({"a": Interval("days", 1, 5, series="q"), "b": Interval("stages", 1, 5, series="q")},
     "series_across_axes", {("q",)}),
], ids=["empty", "inverted", "extension_before_end", "extension_without_end", "extension_of_no_end",
        "start_and_no_start", "end_and_no_end", "series_across_axes"])
def test_must_fail_each_axiom_fires(world, axiom, rows, tmp_path):
    got = evaluate(world, {}, tmp_path)
    assert got[axiom] == rows
    assert all(not got[other] for other in AXIOMS if other != axiom)


def test_an_extension_that_stops_at_the_end_is_allowed(tmp_path):
    got = evaluate({"a": Interval("days", 1, 9, extension_end=9)}, {"r": ("days", 9, 0)}, tmp_path)
    assert not any(got[a] for a in AXIOMS) and got["judgement"] == {("a", "r", "negative", "extension_ended")}


def day(text):
    """A date as a position on a line of days: a true day count, so distances are days."""
    return date.fromisoformat(text).toordinal()


def test_the_validity_cases_of_reckon_5a_hold_as_cases(tmp_path):
    """docs/reckon/v0.md §5a: a version's context is a half-open range per axis and a knowledge date. Exactly
    the versions whose context holds at the subject's date and that are known at the cut take part."""
    # param standard_premium: version 1, valid 2025-01-01..<2026-01-01; version 2, valid 2026-01-01.. (no end).
    premium = {"v1": Interval("days", day("2025-01-01"), day("2026-01-01"), known_from=day("2024-09-17"), series="premium"),
               "v2": Interval("days", day("2026-01-01"), known_from=day("2025-09-16"), series="premium", no_end=True)}
    refs = {"last": ("days", day("2025-12-31"), 0), "first": ("days", day("2026-01-01"), 0)}
    got = evaluate(premium, refs, tmp_path)
    assert got["holds_at"] == {("v1", "last"), ("v2", "first")}          # ..< is half-open: one version each day
    # The spec case "December in January": a December date, asked with a knowledge cut of 15 January.
    norm = {"v1": Interval("days", day("2025-01-01"), day("2026-01-01"), known_from=day("2024-09-17"), series="norm"),
            "v2": Interval("days", day("2026-01-01"), known_from=day("2025-09-16"), series="norm", no_end=True),
            "v3": Interval("days", day("2025-12-01"), day("2026-01-01"), known_from=day("2026-01-20"), series="norm")}
    got = evaluate(norm, {"month": ("days", day("2025-12-01"), 0), "cut": ("days", day("2026-01-15"), 0)}, tmp_path)
    holds = {i for i, r in got["holds_at"] if r == "month"}
    known = {i for i, r in got["known_at"] if r == "cut"}
    assert holds == {"v1", "v3"} and known == {"v1", "v2"} and holds & known == {"v1"}   # v3 is known after the cut
    # v2 is written `2026-01-01..`: a stated "no end". It has no span, so only v1 and v3 are related.
    assert got["allen"] == {("v3", "v1", "finishes"), ("v1", "v3", "finished_by")}
    # The stage axis: during stap-1..<stap-2 and during stap-2.. are ranges of ranks on a line of stages.
    stages = {"v1": Interval("stages", 1, 2, series="setup"), "v2": Interval("stages", 2, series="setup", no_end=True)}
    got = evaluate(stages, {"s1": ("stages", 1, 0), "s2": ("stages", 2, 0), "s3": ("stages", 3, 0)}, tmp_path)
    assert got["holds_at"] == {("v1", "s1"), ("v2", "s2"), ("v2", "s3")}


def test_swapped_bounds_are_a_failing_control():
    """The comparison is sensitive to direction: the reference with start and end swapped differs."""
    world, refs = {"a": Interval("days", 10, 20)}, {"r": ("days", 15, 0)}
    swapped = {"a": Interval("days", 20, 10)}
    assert as_text(batch_eval(program(), tables(world, refs)))["holds_at"] != as_text(reference(swapped, refs))["holds_at"]


POSITION = st.integers(-6, 6)
BOUND = st.none() | POSITION
INTERVALS = st.dictionaries(
    st.sampled_from("abcdef"),
    st.builds(Interval, line=st.sampled_from(["days", "stages"]), start=BOUND, end=BOUND, extension_end=BOUND,
              known_from=BOUND, series=st.none() | st.sampled_from(["p", "q"]), no_start=st.booleans(),
              no_end=st.booleans()), max_size=6)
REFERENCES = st.dictionaries(st.sampled_from(["r", "s", "t"]),
                             st.tuples(st.sampled_from(["days", "stages"]), POSITION, st.integers(0, 4)), max_size=3)


@settings(max_examples=60)
@given(intervals=INTERVALS, references=REFERENCES)
def test_axioms_and_rules_agree_with_the_reference_on_any_world(intervals, references, tmp_path_factory):
    """Property (Hypothesis): on any finite world every engine equals the reference, and the laws hold. The
    strategy draws starts ahead of a reference and missing knowledge times. Where no bound is contradicted: one
    judgement per interval and reference on one line, the one the decision tree of RV-C18 gives; a tone that
    reassures exactly where holds_at has a row (RV-C18); and an interval that holds has begun_at and has not
    ended_at. An interval without known_from has no known_at row and is named by the absence. An interval
    whose end nobody recorded is unknown, or has not begun before a stated start, and has no holds_at or
    ended_at row; one whose start nobody recorded has no begun_at or holds_at row. Allen's
    relations are exhaustive and exclusive on the spans of a series, and each has its inverse."""
    got = evaluate(intervals, references, tmp_path_factory.mktemp("time"))
    sound = set(intervals) - {i for i, in got["bound_contradicted"]}
    pairs = {(i, r) for i, v in intervals.items() for r, ref in references.items() if v.line == ref[0]}
    assert {(i, r) for i, r, *_ in got["judgement"]} == pairs                       # at least one each
    assert sorted((i, r) for i, r, *_ in got["judgement"] if i in sound) == sorted(p for p in pairs if p[0] in sound)
    assert all(REASONS[why] == v for *_, v, why in got["judgement"])
    tree = {(i, r, *ordered(intervals[i], references[r][1], references[r][2])) for i, r in pairs if i in sound}
    assert {row for row in got["judgement"] if row[0] in sound} == tree
    assert {(i, r) for i, r, v, why in got["judgement"] if (v, why) in REASSURING and i in sound} == \
        {(i, r) for i, r in got["holds_at"] if i in sound}
    silent = {i for i, v in intervals.items() if v.known_from is None}
    assert {(i,) for i in silent} == got["known_from_not_recorded"] and not {i for i, _ in got["known_at"]} & silent
    assert got["holds_at"] <= got["begun_at"]
    assert not {(i, r) for i, r in got["holds_at"] & got["ended_at"] if i in sound}
    assert got["in_extension"] <= got["ended_at"]
    no_end = {i for i, in got["end_not_recorded"]}
    no_start = {i for i, in got["start_not_recorded"]}
    assert {v for i, _, v, _ in got["judgement"] if i in no_end} <= {"unknown", "not_begun"}   # RV-C18: before a stated start
    assert not {i for i, _ in got["holds_at"] | got["ended_at"]} & no_end
    assert not {i for i, _ in got["holds_at"] | got["begun_at"]} & no_start
    related = {(a, b) for a, b, _ in got["allen"]}
    spans = {i: q for i, q, *_ in got["span"]}
    assert len(related) == len(got["allen"])                                        # exclusive
    assert related == {(a, b) for a in spans for b in spans if a != b and spans[a] == spans[b]}   # exhaustive
    assert all((b, a, INVERSE[name]) in got["allen"] for a, b, name in got["allen"])


@settings(max_examples=100)
@given(intervals=INTERVALS, references=REFERENCES, shift=st.integers(-50, 50), stretch=st.integers(1, 5))
def test_what_a_reading_of_positions_must_preserve(intervals, references, shift, stretch):
    """The README's claim on readings. Every relation but the split between attention and positive reads only
    the order of positions, so any strictly increasing reading (here p -> stretch * p + shift, as a day
    written YYYYMMDD is for dates) gives the same rows. The horizon is a distance: a reading that keeps
    distances (stretch = 1) gives the same judgement too."""
    def read(p, by):
        return None if p is None else by * p + shift

    def moved(by):
        return ({i: Interval(v.line, read(v.start, by), read(v.end, by), read(v.extension_end, by),
                             read(v.known_from, by), v.series, v.no_start, v.no_end) for i, v in intervals.items()},
                {r: (line, read(p, by), h) for r, (line, p, h) in references.items()})

    plain, stretched, shifted = reference(intervals, references), reference(*moved(stretch)), reference(*moved(1))
    for name in DERIVED:
        if name == "span":
            assert {(i, q) for i, q, *_ in stretched[name]} == {(i, q) for i, q, *_ in plain[name]}
        elif name == "judgement":
            settled = lambda rows: {row for row in rows if row[2] in ("negative", "no_end", "unknown")}  # noqa: E731
            assert settled(stretched[name]) == settled(plain[name]) and shifted[name] == plain[name]
        else:
            assert stretched[name] == plain[name], name


def bound_domain(tmp_path):
    """A domain that pins the theory and has a kind of its own that is an Interval, with five stretches."""
    import yaml
    from rezono_compiler import modules

    domain = tmp_path / "bound"
    for folder in ("schema", "labels", "facts"):
        (domain / folder).mkdir(parents=True)
    (domain / "pack.yaml").write_text(yaml.safe_dump({
        "name": "bound", "version": "0.1.0", "default_language": "en",
        "imports": [{"name": "std-time", "path": str(THEORY), "sha256": modules.pack_hash(THEORY)}]}), "utf-8")
    (domain / "schema" / "bound.yaml").write_text(yaml.safe_dump({
        "id": "https://rezono.example/bound", "name": "bound", "prefixes": {"linkml": "https://w3id.org/linkml/"},
        "imports": ["linkml:types", "std-time:time"], "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {"Stretch": {"is_a": "Interval", "attributes": {"title": {}}}}}), "utf-8")
    (domain / "labels" / "en.yaml").write_text("stretch: stretch\nstretch.title: title\n", "utf-8")
    (domain / "channels.yaml").write_text("kinds:\n  - {kind: stretch, shape: rect}\n", "utf-8")
    (domain / "facts" / "all.yaml").write_text(yaml.safe_dump({
        "axis": [{"id": "days"}],
        "reference_point": [{"id": "now", "on_axis": "days", "position": 15, "horizon": 3}],
        "stretch": [{"id": "a", "title": "A", "on_axis": "days", "start": 10, "end": 20},
                    {"id": "b", "title": "B", "on_axis": "days", "start": 1, "end": 17},
                    {"id": "c", "title": "C", "on_axis": "days", "start": 12},
                    {"id": "d", "title": "D", "on_axis": "days", "start": 9, "end": 3},
                    {"id": "e", "title": "E", "on_axis": "days", "start": 12, "unbounded": ["end"]}]}), "utf-8")
    return domain


def test_a_domain_kind_that_is_an_interval_gets_the_theory_through_the_ordinary_compiler(tmp_path):
    """The binding that runs today, without view lowering: a domain pins the theory, and a kind of its own is an
    Interval (is_a). Its elements are in the theory's tables, so the theory's rules, axioms and questions hold
    for them through the ordinary compiler. This is the inclusion view; a view with other names waits for
    the lowering (docs/compiler.md, theories and views)."""
    from rezono_compiler import batch, scenarios

    domain = bound_domain(tmp_path)
    model = pack.read(domain)
    assert model.kinds["stretch"].parent == "interval" and model.meta["theory"] is False
    prog = ir.load(model.rules)
    (_, rows), = scenarios.states(model, domain)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    got = as_text(batch.read(con, prog))
    assert got["holds_at"] == {("a", "now"), ("b", "now"), ("e", "now")}     # c has begun; nobody recorded its end
    assert {(i, v) for i, _, v, _ in got["judgement"]} == {
        ("a", "positive"), ("b", "attention"), ("c", "unknown"), ("d", "negative"), ("e", "no_end")}
    assert got["end_not_recorded"] == {("c",)}
    assert got["interval_inverted"] == {("d",)}      # the axiom blocks the domain's own row


def test_must_fail_a_domain_rule_that_negates_holds_at_is_refused(tmp_path):
    """REVIEW (18)'s P2 on #654, with RV-C18: holds_at is open, because it reads a bound that may not be
    recorded. A domain rule that concludes "does not hold" from a missing holds_at row would read an unknown
    as a no, so the ordinary compiler refuses it (W6). The same rule as an @absence relation is allowed: it
    then speaks about what is recorded, and is closed."""
    domain = bound_domain(tmp_path)
    (domain / "rules").mkdir()
    rule = ".decl lapsed(i: symbol, r: symbol)\nlapsed(i, r) :- begun_at(i, r), !holds_at(i, r).\n"
    (domain / "rules" / "own.dl").write_text(rule, "utf-8")
    with pytest.raises(pack.CompileError, match="negation_over_open"):
        pack.read(domain)
    (domain / "rules" / "own.dl").write_text("// @absence\n" + rule, "utf-8")
    prog = ir.load(pack.read(domain).rules)
    assert prog.relations["holds_at"].world == "open" and prog.relations["lapsed"].world == "closed"
