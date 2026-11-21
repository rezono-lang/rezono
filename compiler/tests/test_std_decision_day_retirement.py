"""Retire day-number slots and coupling rules from std-decision (decisions/standard-packs-everywhere.md,
sections 1.3 and 1.4 step 6; decisions/no-green-by-cheapest-route.md).

Enforces the end state of the date migration for packs/std-decision (both live and staged candidate)
and its importing packs via compiled schema models and rule IR:
- no *_day slots or ReferenceDate.day remain in packs/std-decision (live or staged candidate);
- ReferenceDate.date is a required native date slot;
- the four date/day-number coupling schema rules on Decision are gone (only the withdrawn-decision rule remains);
- the compiled rules of packs/std-decision (live and staged candidate) read only the native date relations;
- no importing pack's facts write Decision.valid_from_day, Decision.valid_until_day, or ReferenceDate.day;
- packs/std-decision compiles, rejects a ReferenceDate missing `date`, and evaluates in_force_on from pure dates.
"""

from __future__ import annotations

from contextlib import closing

import pytest
import yaml

from candidate_pack import admitted, isolated_standard_pack
from rezono_compiler import batch, emit, facts, pack
from rezono_compiler import rules as ir
from support import REPO

STD = REPO / "packs" / "std-decision"
ROOTS = ("build", "examples", "packs", "run")
DATE_RELATIONS = {"decision__valid_from", "decision__valid_until", "reference_date__date"}
RETIRED_SLOTS = ("valid_from_day", "valid_until_day")
RETIRED_RELATIONS = {"decision__valid_from_day", "decision__valid_until_day", "reference_date__day"}

DECISIONS = [
    {"id": "d1", "title": "first", "state": "in_force", "decider": ["board"], "valid_from": "2026-01-01"},
    {"id": "d2", "title": "successor", "state": "in_force", "decider": ["board"], "valid_from": "2026-02-01",
     "supersedes": ["d1"]},
    {"id": "d3", "title": "bounded", "state": "in_force", "decider": ["board"], "valid_from": "2026-01-01",
     "valid_until": "2026-02-15"},
]
REFERENCE_DATES = [
    {"id": "r1", "title": "15 January 2026", "date": "2026-01-15"},
    {"id": "r2", "title": "15 February 2026", "date": "2026-02-15"},
]


def _importers():
    """All pack directories under the repository pack roots whose pack.yaml imports std-decision."""
    found = []
    for root in ROOTS:
        for manifest in sorted((REPO / root).rglob("pack.yaml")):
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            names = {entry.get("name") for entry in doc.get("imports") or () if isinstance(entry, dict)}
            if "std-decision" in names:
                found.append(manifest.parent)
    return found


def _assert_pack_retired_day_numbers(model: pack.Pack, label: str) -> ir.Program:
    """Assert that a compiled std-decision Pack (live or candidate) has no day-number slots, coupling rules, or reads."""
    day_slots = sorted(
        f"{kind_name}.{slot_name}"
        for kind_name, kind_def in model.kinds.items()
        for slot_name in kind_def.slots
        if slot_name.endswith("_day")
    )
    assert not day_slots, f"{label} still keeps *_day slots: {day_slots}"

    ref_slots = model.kinds["reference_date"].slots
    assert "day" not in ref_slots, f"{label} ReferenceDate still keeps retired integer day-number slot `day`"
    date_slot = ref_slots.get("date")
    assert date_slot is not None and date_slot.range == "date" and date_slot.required is True, (
        f"{label} ReferenceDate.date must be a required native date slot, got {date_slot!r}"
    )

    decision_rules = model.kinds["decision"].rules
    coupling_rules = [
        rule.name
        for rule in decision_rules
        if any(
            cond.slot in RETIRED_SLOTS
            for cond in (*rule.pre, *rule.post, *rule.otherwise)
        )
    ]
    assert not coupling_rules, f"{label} Decision still keeps date/day-number coupling schema rules: {coupling_rules}"
    assert len(decision_rules) == 1, (
        f"{label} Decision should keep only the withdrawn-decision schema rule, found {len(decision_rules)}"
    )

    program = ir.load(model.rules)
    used = set(program.base_used())
    assert DATE_RELATIONS <= used, f"{label} rules must read native dates, missing: {sorted(DATE_RELATIONS - used)}"
    assert not (used & RETIRED_RELATIONS), (
        f"{label} rules still read retired day-number relations: {sorted(used & RETIRED_RELATIONS)}"
    )
    return program


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/standard-packs-everywhere.md: sections 1.3 and 1.4 step 6 "
        "(decisions/no-green-by-cheapest-route.md). Retire Decision.valid_from_day, "
        "Decision.valid_until_day, ReferenceDate.day and the four date/day-number "
        "coupling schema rules from packs/std-decision (and its staged candidate), "
        "make ReferenceDate.date required, remove *_day / ReferenceDate.day fields "
        "from std-decision consumer facts and re-pin every importing pack.yaml. "
        "Waits for compiler/tests/test_std_decision_dates.py--test_std_decision_rules_read_dates, "
        "examples/subsidy/test_subsidy_dates.py--test_subsidy_schema_has_no_day_numbers, "
        "examples/platform/test_platform_release_dates.py--test_runs_orders_releases_by_their_sourced_date "
        "and examples/platform/test_support_window_dates.py--test_support_query_retires_as_of_day_for_native_date, "
        "and for a preparatory planner PR that restates *_day rows and protected test assertions "
        "(such as compiler/tests/test_std_decision.py, examples/platform/test_five_scenes.py, and "
        "loop/tests/test_build_decision_capture.py) before step 6 lifts this mark."
    ),
)
def test_std_decision_retires_day_numbers_and_coupling_rules(tmp_path):
    # 1. Live packs/std-decision schema, rules, and compiled IR have no *_day slots, coupling rules, or reads.
    model = pack.read(STD)
    program = _assert_pack_retired_day_numbers(model, "packs/std-decision")

    # 2. Staged Rezono candidate compiles cleanly with the exact same retired-day-number contract.
    cand_dir = isolated_standard_pack(STD, tmp_path, "candidate", "decision")
    with admitted(cand_dir):
        cand_model = pack.read(cand_dir)
        _assert_pack_retired_day_numbers(cand_model, "packs/std-decision/candidate")

    # 3. No fact file in packs/std-decision or its importing packs may write retired day numbers.
    legacy_facts: list[str] = []
    for pack_dir in [STD, *_importers()]:
        for fact_file in sorted(pack_dir.rglob("facts/*.yaml")):
            rel_parts = fact_file.relative_to(pack_dir).parts
            if "expected" in rel_parts:
                continue
            data = yaml.safe_load(fact_file.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                continue
            rel = fact_file.relative_to(REPO).as_posix()
            for row in data.get("decision") or ():
                if isinstance(row, dict):
                    for bad in RETIRED_SLOTS:
                        if bad in row:
                            legacy_facts.append(f"{rel}: decision {row.get('id')!r} writes {bad}")
            for row in data.get("reference_date") or ():
                if isinstance(row, dict):
                    if "day" in row:
                        legacy_facts.append(f"{rel}: reference_date {row.get('id')!r} writes day")
                    if "date" not in row:
                        legacy_facts.append(f"{rel}: reference_date {row.get('id')!r} missing required date")
    assert not legacy_facts, "std-decision consumers still write retired day numbers:\n" + "\n".join(legacy_facts)

    # 4. Pure-date runtime check: std-decision evaluates in_force_on from dates alone and enforces ReferenceDate.date.
    data = {"decision": DECISIONS, "reference_date": REFERENCE_DATES}
    with closing(batch.connect(program, facts.rows_of(model, data))) as db:
        batch.compute(db, program)
        derived = batch.read(db, program)
    assert set(derived.get("in_force_on", ())) == {("d1", "r1"), ("d2", "r2"), ("d3", "r1")}

    missing_date = tmp_path / "missing_date.yaml"
    missing_date.write_text("reference_date:\n  - {id: r0, title: missing date}\n", encoding="utf-8")
    compiled = emit.compile_pack(model)
    import duckdb

    with closing(duckdb.connect()) as db:
        db.execute(compiled["batch/tables.sql"])
        loaded = facts.load(model, missing_date)
        for table, rows in loaded.items():
            if rows:
                db.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" * len(rows[0]))})', rows)
        db.execute(compiled["batch/integrity.sql"])
        missing_rows = db.execute('SELECT subject FROM "reference_date__date__required"').fetchall()
    assert {subject for (subject,) in missing_rows} == {"r0"}
