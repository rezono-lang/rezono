"""std-decision reads its dates, not their day numbers (decisions/standard-packs-everywhere.md, section 1).

The expectations come from the decision record of std-decision (schema/decision.yaml and its README): a decision
applies from valid_from and no longer on valid_until, a successor replaces it from the successor's own first
day, a proposal never takes effect, and a window that ends on or before its start is inverted. The day numbers
are worked out here by hand from the calendar, independently of the engine.
"""

import re
from contextlib import closing

import pytest
import yaml

from support import REPO
from rezono_compiler import batch, facts, pack
from rezono_compiler import rules as ir

STD = REPO / "packs" / "std-decision"
DATES = {"decision__valid_from", "decision__valid_until", "reference_date__date"}
NUMBERS = ("decision__valid_from_day", "decision__valid_until_day", "reference_date__day")
NUMBER_READ = re.compile(r"\b(" + "|".join(NUMBERS) + r")\s*\(")
ROOTS = ("build", "examples", "packs", "run")

DECISIONS = [
    {"id": "d1", "title": "first", "state": "in_force", "decider": ["board"], "valid_from": "2026-01-01"},
    {"id": "d2", "title": "successor", "state": "in_force", "decider": ["board"], "valid_from": "2026-02-01",
     "supersedes": ["d1"]},
    {"id": "d3", "title": "inverted", "state": "in_force", "valid_from": "2026-03-01", "valid_until": "2026-02-01"},
    {"id": "d4", "title": "proposal", "state": "proposed", "valid_from": "2026-01-01"},
    {"id": "d5", "title": "bounded", "state": "in_force", "decider": ["board"], "valid_from": "2026-01-01",
     "valid_until": "2026-02-15"},
]
REFERENCE_DATES = [
    {"id": "r1", "title": "15 January 2026", "date": "2026-01-15"},
    {"id": "r0", "title": "1 February 2026", "date": "2026-02-01"},
    {"id": "r2", "title": "15 February 2026", "date": "2026-02-15"},
    {"id": "r3", "title": "1 April 2026", "date": "2026-04-01"},
]


def importers():
    """The pack directories under the repository's pack roots whose pack.yaml imports std-decision."""
    found = []
    for root in ROOTS:
        for manifest in sorted((REPO / root).rglob("pack.yaml")):
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            names = {entry.get("name") for entry in doc.get("imports") or () if isinstance(entry, dict)}
            if "std-decision" in names:
                found.append(manifest.parent)
    return found


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M3: decisions/standard-packs-everywhere.md, sections 1.2 to 1.4, step 3. Let a .dl rule pass a variable "
    "bound to a native date column to @days (the IR days assignment that views already produce), give "
    "ReferenceDate a required Date slot `date`, make the rules of packs/std-decision (and its staged candidate) "
    "read valid_from, valid_until and reference_date__date, drop the four schema rules that tie a date to its "
    "day number, and make build/rules/policy_date.dl and run/packs/probe-profiles/rules/budgets.dl read the "
    "date. Re-pin std-decision in every importing pack.yaml. Step 2 (a planner gives the tests that feed "
    "std-decision rows their dates) must have landed first; report to the planner if it has not."))
def test_std_decision_rules_read_dates():
    model = pack.read(STD)
    program = ir.load(model.rules)
    used = set(program.base_used())
    assert DATES <= used, f"std-decision rules must read the dates, missing: {sorted(DATES - used)}"
    assert not used & set(NUMBERS), f"std-decision rules still read day numbers: {sorted(used & set(NUMBERS))}"

    readers = []
    for directory in importers():
        for source in sorted((directory / "rules").glob("*.dl")):
            for relation in NUMBER_READ.findall(source.read_text(encoding="utf-8")):
                readers.append(f"{source.relative_to(REPO)}: {relation}")
    assert not readers, f"Rules of std-decision importers still read day numbers: {readers}"

    data = {"decision": DECISIONS, "reference_date": REFERENCE_DATES}
    with closing(batch.connect(program, facts.rows_of(model, data))) as db:
        batch.compute(db, program)
        derived = batch.read(db, program)

    # d1 applies until its successor d2 takes effect on 1 February; d2 applies from its own first day on; d3 took
    # effect on 1 April but had ended (its end lies before its start); d4 is only proposed; d5 applies up to, and
    # not on, 15 February.
    assert set(derived.get("in_force_on", ())) == {("d1", "r1"), ("d2", "r0"), ("d2", "r2"), ("d2", "r3"),
                                           ("d5", "r1"), ("d5", "r0")}
    assert set(derived.get("replaced", ())) == {("d1", "d2", "r0"), ("d1", "d2", "r2"), ("d1", "d2", "r3")}
    assert set(derived.get("ended", ())) == {("d3", "r0"), ("d3", "r2"), ("d3", "r3"), ("d5", "r2"), ("d5", "r3")}
    assert set(derived.get("window_inverted", ())) == {("d3",)}
    assert not set(derived.get("superseded_in_force", ()))
