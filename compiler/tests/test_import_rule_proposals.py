"""Import review cases over the pinned neutral fixture and authored rule candidates."""

from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_compiler import batch, facts, modules, pack, rules, rules_dl, sources
from rezono_compiler.__main__ import main
import souffle


NEUTRAL = Path(__file__).resolve().parents[2] / "tests/fixtures/neutral"
TARGET = "item__quantity"
OUTPUT = "proposed_quantity"
DECLARATION = ".decl proposed_quantity(item: symbol, quantity: number)\n"
FULL = 'proposed_quantity(i, 7) :- item(i), i != "item-b".\n'
PARTIAL = 'proposed_quantity(i, 7) :- item(i), i != "item-b", i != "item-d".\n'
ALL_ITEMS = "proposed_quantity(i, 7) :- item(i).\n"
REMAINDER = ("item-d", 7)
EXCESS = ("item-b", 7)
REASON = "import.exception.authored"
ORIGIN = {"kind": "pack", "name": "facts/rows.yaml", "position": "facts/rows.yaml#/item/3/quantity",
          "ownership": "first_party"}


@dataclass(frozen=True)
class Case:
    directory: Path
    candidate: Path
    original: set[tuple[str, int]]
    members: list[tuple[str]]


def row_ref(values):
    return {"relation": TARGET, "key": canonical_json(values)}


def refs(rows):
    return [row_ref(row) for row in sorted(rows)]


def prepare(tmp_path, clause, *, extra=48, all_quantities=False, origin=None):
    directory = modules.copy_closure(NEUTRAL, tmp_path / "pinned")
    fact_file = directory / "facts/rows.yaml"
    contents = yaml.safe_load(fact_file.read_bytes())
    ids = [f"item-extra-{i:03d}" for i in range(extra)]
    contents["item"].extend({"id": id_, "group": "group-a", "labels": ["first"], "quantity": 7} for id_ in ids)
    expected = {(id_, 7) for id_ in ["item-a", "item-c", "item-d", *ids]}
    if all_quantities:
        contents["item"][1]["quantity"] = 7
        expected.add(EXCESS)
    fact_file.write_bytes(yaml.safe_dump(contents, sort_keys=False).encode("utf-8"))

    if origin is not None:
        sidecar = directory / "facts/rows.sources.yaml"
        metadata = yaml.safe_load(sidecar.read_bytes())
        authored = {"row": row_ref(REMAINDER), "reason": REASON, "sources": [origin]}
        metadata["rows"] = [authored]
        sidecar.write_bytes(yaml.safe_dump(metadata, sort_keys=False).encode("utf-8"))
        declared = sources.file_entries(pack.read(directory), fact_file)
        if authored not in declared:
            pytest.fail("The neutral fixture lost its explicit source entry.")

    actual = facts.load(pack.read(directory), fact_file)
    if set(actual[TARGET]) != expected:
        pytest.fail("The typed neutral rows differ from the independently authored original set.")
    candidate = tmp_path / "proposal.dl"
    candidate.write_bytes((DECLARATION + clause).encode("utf-8"))
    return Case(directory, candidate, expected, sorted(actual["item"]))


def verify_fixture(case, expected):
    """Check the candidate against actual held-out inputs with the existing evaluators."""
    text = case.candidate.read_text(encoding="utf-8")
    program = rules.load(rules_dl.read_program(text, case.candidate.name, {"item": [("id", "string")]}, "proposal"))
    held_out = {"item": case.members}
    with closing(batch.connect(program, held_out, threads=1)) as connection:
        batch.compute(connection, program)
        duckdb = batch.read(connection, program)[OUTPUT]
    # The compiler CI installs the pinned binary. The fixture still runs on local machines with DuckDB alone.
    if shutil.which("souffle"):
        other = souffle.run(program, held_out, program_text=souffle.source(program, [text]))[OUTPUT]
        if duckdb != other:
            pytest.fail("DuckDB and Soufflé disagree on the pinned candidate inputs.")
    if {(id_, int(quantity)) for id_, quantity in duckdb} != expected:
        pytest.fail("The executable candidate does not match the independently authored row set.")


def fact_pin(case):
    return canonical_sha256({path.relative_to(case.directory).as_posix(): sha256_hex(path.read_bytes())
                             for path in sorted((case.directory / "facts").glob("*.yaml"))})


def check(case, capsys, status):
    pin = fact_pin(case)
    code = main(["check-rule-proposal", str(case.directory), TARGET, str(case.candidate)])
    try:
        report = json.loads(capsys.readouterr().out)
    except json.JSONDecodeError as error:
        raise AssertionError("The compiler should report the result as a JSON object.") from error
    assert isinstance(report, dict)
    assert (code, report.get("status")) == (0 if status == "eligible" else 1, status)
    assert report.get("relation") == TARGET
    assert report.get("definition_sha256") == modules.pack_hash(case.directory)
    assert report.get("facts_sha256") == pin == fact_pin(case)
    assert report.get("candidate_sha256") == sha256_hex(case.candidate.read_bytes())
    return report


@pytest.mark.xfail(strict=True, raises=(AssertionError, SystemExit),
                   reason="Check rule proposals through the compiler CLI. Read decisions/import-rule-proposals.md. "
                          "Compare the exact withheld relation in DuckDB and Soufflé and report the complete explanation.")
def test_rule_proposal_explains_the_original_set(tmp_path, capsys):
    case = prepare(tmp_path, FULL)
    verify_fixture(case, case.original)
    report = check(case, capsys, "eligible")
    assert report.get("explained") == refs(case.original)
    assert report.get("retained") == []


@pytest.mark.xfail(strict=True, raises=(AssertionError, SystemExit),
                   reason="Keep a verified remainder in compiler rule proposal results. "
                          "Read decisions/import-rule-proposals.md and the SourceEntry in contracts/source.yaml.")
def test_rule_proposal_keeps_the_sourced_remainder(tmp_path, capsys):
    case = prepare(tmp_path, PARTIAL, origin=ORIGIN)
    explained = case.original - {REMAINDER}
    verify_fixture(case, explained)
    report = check(case, capsys, "eligible")
    assert report.get("explained") == refs(explained)
    assert report.get("retained") == [{"row": row_ref(REMAINDER), "sources": [ORIGIN], "reason": REASON}]


@pytest.mark.xfail(strict=True, raises=(AssertionError, SystemExit),
                   reason="Refuse excess rows in the compiler rule proposal command. "
                          "Read decisions/import-rule-proposals.md and report the actual counterexample.")
def test_rule_proposal_refuses_one_excess_row(tmp_path, capsys):
    case = prepare(tmp_path, ALL_ITEMS)
    verify_fixture(case, case.original | {EXCESS})
    assert check(case, capsys, "excess_rows").get("excess") == refs({EXCESS})


@pytest.mark.xfail(strict=True, raises=(AssertionError, SystemExit),
                   reason="Charge required input facts in the compiler rule proposal byte comparison. "
                          "Read decisions/import-rule-proposals.md and use canonical typed row bytes.")
def test_rule_proposal_charges_needed_facts(tmp_path, capsys):
    case = prepare(tmp_path, ALL_ITEMS, extra=8, all_quantities=True)
    verify_fixture(case, case.original)
    rule_bytes = len(canonical_bytes({case.candidate.name: case.candidate.read_text(encoding="utf-8")}))
    support_bytes = len(canonical_bytes({"item": case.members}))
    original_bytes = len(canonical_bytes(sorted(case.original)))
    if not rule_bytes < original_bytes <= rule_bytes + support_bytes:
        pytest.fail("The fixture must fail the size bound because of its required facts.")
    report = check(case, capsys, "not_smaller")
    assert report.get("sizes") == {"candidate_bytes": rule_bytes + support_bytes, "explained_bytes": original_bytes}


@pytest.mark.xfail(strict=True, raises=(AssertionError, SystemExit),
                   reason="Report unverified retained origins as gaps in the compiler rule proposal command. "
                          "Read decisions/import-rule-proposals.md. A reason alone cannot establish a source.")
def test_rule_proposal_reports_unverified_origin_as_a_gap(tmp_path, capsys):
    # The locator names an actual record, but that record has no quantity.
    wrong_origin = ORIGIN | {"position": "facts/rows.yaml#/item/1/quantity"}
    case = prepare(tmp_path, PARTIAL, origin=wrong_origin)
    verify_fixture(case, case.original - {REMAINDER})
    report = check(case, capsys, "provenance_gap")
    assert report.get("gaps") == refs({REMAINDER})
    assert report.get("retained") == []
