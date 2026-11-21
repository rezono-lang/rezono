"""Retire day-number slots and coupling rules from std-decision (decisions/standard-packs-everywhere.md,
sections 1.3 and 1.4 step 6; decisions/no-green-by-cheapest-route.md).

Enforces the end state of the date migration for packs/std-decision and its importing packs:
- no *_day slots or ReferenceDate.day remain in packs/std-decision schema, rules, or staged candidate;
- ReferenceDate.date is a required native date slot;
- the four date/day-number coupling schema rules on Decision are gone (only the withdrawn-decision rule remains);
- no importing pack's facts write Decision.valid_from_day, Decision.valid_until_day, or ReferenceDate.day;
- packs/std-decision compiles, rejects a ReferenceDate missing `date`, and evaluates in_force_on from pure dates.
"""

from __future__ import annotations

from contextlib import closing
import re

import pytest
import yaml

from rezono_compiler import batch, emit, facts, pack
from rezono_compiler import rules as ir
from support import REPO

STD = REPO / "packs" / "std-decision"
SCHEMA = STD / "schema" / "decision.yaml"
CANDIDATE = STD / "candidate" / "decision.rezono"
ROOTS = ("build", "examples", "packs", "run")
RETIRED_SLOTS = ("valid_from_day", "valid_until_day")
RETIRED_RELATIONS = ("decision__valid_from_day", "decision__valid_until_day", "reference_date__day")
RETIRED_REF_PATTERN = re.compile(r"\b(" + "|".join((*RETIRED_SLOTS, *RETIRED_RELATIONS)) + r")\b")

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
        "Waits for compiler/tests/test_std_decision_dates.py--test_std_decision_rules_read_dates."
    ),
)
def test_std_decision_retires_day_numbers_and_coupling_rules(tmp_path):
    doc = yaml.safe_load(SCHEMA.read_text(encoding="utf-8")) or {}
    classes = doc.get("classes") or {}

    # 1. No *_day slots anywhere in packs/std-decision/schema/decision.yaml, and no ReferenceDate.day.
    day_slots = [
        f"{cls_name}.{slot_name}"
        for cls_name, cls_def in classes.items()
        for slot_name in (cls_def.get("attributes") or {})
        if slot_name.endswith("_day")
    ]
    assert not day_slots, f"packs/std-decision schema still keeps *_day slots: {sorted(day_slots)}"

    ref_attrs = (classes.get("ReferenceDate") or {}).get("attributes") or {}
    assert "day" not in ref_attrs, "ReferenceDate still keeps retired integer day-number slot `day`"
    date_slot = ref_attrs.get("date") or {}
    assert date_slot.get("range") == "date" and date_slot.get("required") is True, (
        f"ReferenceDate.date must be a required native date slot, got {date_slot!r}"
    )

    # 2. The four date <-> day-number coupling schema rules on Decision are gone.
    decision_rules = (classes.get("Decision") or {}).get("rules") or []
    coupling_rules = [
        idx + 1
        for idx, rule in enumerate(decision_rules)
        if RETIRED_REF_PATTERN.search(yaml.safe_dump(rule))
    ]
    assert not coupling_rules, (
        f"Decision still keeps date/day-number coupling schema rules at positions {coupling_rules}"
    )
    assert len(decision_rules) == 1, (
        f"Decision should keep only the withdrawn-decision schema rule, found {len(decision_rules)}"
    )

    # 3. Neither rules/*.dl nor candidate/decision.rezono may mention retired day-number slots or relations.
    for dl_path in sorted((STD / "rules").glob("*.dl")):
        hits = RETIRED_REF_PATTERN.findall(dl_path.read_text(encoding="utf-8"))
        assert not hits, f"{dl_path.relative_to(REPO)} still references retired day numbers: {sorted(set(hits))}"

    candidate_text = CANDIDATE.read_text(encoding="utf-8")
    candidate_hits = RETIRED_REF_PATTERN.findall(candidate_text)
    assert not candidate_hits, (
        f"{CANDIDATE.relative_to(REPO)} still references retired day numbers: {sorted(set(candidate_hits))}"
    )
    assert not re.search(r"^\s+day\s*:\s*Int\b", candidate_text, re.MULTILINE), (
        f"{CANDIDATE.relative_to(REPO)} still declares ReferenceDate.day: Int"
    )
    assert not re.search(r"^\s+date\s*:\s*Date\?", candidate_text, re.MULTILINE), (
        f"{CANDIDATE.relative_to(REPO)} still keeps ReferenceDate.date optional (`Date?`) instead of required `Date`"
    )

    # 4. No fact file in packs/std-decision or its importing packs may write retired day numbers.
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

    # 5. Pure-date runtime check: std-decision evaluates in_force_on from dates alone and enforces ReferenceDate.date.
    model = pack.read(STD)
    assert model.kinds["reference_date"].slots["date"].required is True
    assert "day" not in model.kinds["reference_date"].slots
    assert not (set(RETIRED_SLOTS) & set(model.kinds["decision"].slots))

    program = ir.load(model.rules)
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
