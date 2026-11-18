"""Replay the shared neutral cases through the batch compiler and publication."""

import json
from pathlib import Path
from runpy import run_path

import pytest

from rezono_publication import l0, publication


CORPUS = Path(__file__).resolve().parents[2] / "tests/conformance"
replay = run_path(str(CORPUS / "replay.py"))


class UntypedAggregate(AssertionError):
    """The publication reader accepted noninteger text in an integer aggregate."""


@pytest.mark.parametrize("case", replay["cases"]("compiler"))
def test_compiler_replays_neutral_case(case, tmp_path):
    result = replay["play"](case, tmp_path)
    assert replay["read_sum"](case, result.rows, result.witnesses) == case["expect"]


@pytest.mark.xfail(
    strict=True,
    raises=UntypedAggregate,
    reason="Preserve a proved aggregate's integer type through the compiled bundle and publication "
           "schema. Read tests/conformance/value-agg-sum-empty.yaml. Write in compiler/ and publication/.",
)
def test_compiled_conformance_aggregate_refuses_a_nonnumeric_publication_value(tmp_path):
    case = replay["case_file"]("value-agg-sum-empty")
    result = replay["play"](case, tmp_path)
    assert replay["read_sum"](case, result.rows, result.witnesses) == case["expect"]
    subject = case["input"]["select"]["id"]
    relation = case["input"]["rules"]["output"]
    kind, (group_column, value_column) = result.publication_plan["derived"][relation]
    rows = publication.row_json(result.publication_schema, result.publication_plan, {
        "rows": result.rows, "witnesses": result.witnesses, "sources": [],
    })
    (row,) = [row for row in rows if row["$kind"] == kind and row[group_column] == subject]
    assert row[value_column] == case["expect"]["value"]
    l0.read_rows(result.publication_schema, [row])
    invalid_value = "zero"
    wrong = {key: value for key, value in row.items() if key != "$why"}
    wrong |= {"$id": json.dumps([subject, invalid_value], separators=(",", ":")), value_column: invalid_value}
    try:
        l0.read_rows(result.publication_schema, [wrong])
    except l0.L0Error as error:
        assert value_column in str(error) and "integer" in str(error)
    else:
        raise UntypedAggregate(f"{kind}.{value_column} admitted {invalid_value!r}")
