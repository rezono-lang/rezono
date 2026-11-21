"""Replay the shared neutral cases through the batch compiler and publication."""

import json
from pathlib import Path
from runpy import run_path

import pytest

from rezono_compiler import pack, rules
from rezono_publication import l0, publication


CORPUS = Path(__file__).resolve().parents[2] / "tests/conformance"
replay = run_path(str(CORPUS / "replay.py"))


@pytest.mark.parametrize("case", replay["cases"]("compiler"))
def test_compiler_replays_neutral_case(case, tmp_path):
    result = replay["play"](case, tmp_path)
    assert replay["read_sum"](case, result.rows, result.witnesses) == case["expect"]


def test_open_aggregate_requires_explicit_recorded_absence(tmp_path):
    case = replay["case_file"]("value-derived-world-aggregate")
    source = case["input"]["rules"]
    result = replay["play"](case, tmp_path / "recorded")
    relations = rules.load(result.rules).relations
    assert relations["member_measure"].world == "open"
    assert relations[source["output"]].world == "closed"
    assert relations[source["output"]].absence is True
    assert replay["read_sum"](case, result.rows, result.witnesses) == case["expect"]

    assert source["clauses"].count("// @absence\n") == 1
    source["clauses"] = source["clauses"].replace("// @absence\n", "")
    with pytest.raises(pack.CompileError, match="aggregate_over_open"):
        replay["play"](case, tmp_path / "unmarked")

    # The same rows carry equal quantities in the closed slot of the neutral fixture.
    assert source["clauses"].count("item__weight") == 1
    source["clauses"] = source["clauses"].replace("item__weight", "item__quantity")
    closed = replay["play"](case, tmp_path / "closed")
    relations = rules.load(closed.rules).relations
    assert relations["member_measure"].world == "closed"
    assert not relations[source["output"]].absence
    assert replay["read_sum"](case, closed.rows, closed.witnesses) == case["expect"]


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
    (witness,) = [w for w in result.witnesses if w["conclusion"] == {"relation": relation, "key": row["$id"]}]
    # Accept both the legacy opaque URI and the canonical <base>witness/<H> IRI during the transition
    # of publication.py:328 (decisions/publication-conclusion-addresses.md §5); the strict red test in
    # publication/tests/test_conclusion_addresses.py requires the canonical IRI exclusively.
    assert row["$why"]["$id"] in {
        publication.witness_uri(witness),
        publication.witness_uri(witness, result.publication_schema),
    }
    l0.check_schema(result.publication_schema)
    assert l0.read_rows(result.publication_schema, [row]) == [row]
    assert publication.differences(result.publication_schema, result.publication_plan, rows, result.rows) == []

    for value, message in [("zero", "integer"), ("01", "integer"), ("-0", "integer"), (0, "integer"),
                           ("9223372036854775808", "outside"), ("-9223372036854775809", "outside")]:
        wrong = {key: v for key, v in row.items() if key != "$why"}
        wrong |= {"$id": json.dumps([subject, value], separators=(",", ":")), value_column: value}
        with pytest.raises(l0.L0Error, match=rf"\.{value_column}: .*{message}"):
            l0.read_rows(result.publication_schema, [wrong])
