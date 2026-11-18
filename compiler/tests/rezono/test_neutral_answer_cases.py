"""Replay complete neutral answers on the compiled publication schema."""

import json
import os
from pathlib import Path
from runpy import run_path
import subprocess

import pytest

from rezono_compiler import emit, pack
from rezono_publication import l0, publication


ROOT = Path(__file__).resolve().parents[3]
CORPUS = run_path(str(ROOT / "tests/conformance/replay.py"))
DRIVER = Path(__file__).with_name("neutral-answer-cases.mjs")


@pytest.fixture(scope="module")
def neutral_schema():
    compiled = emit.compile_pack(pack.read(CORPUS["NEUTRAL"]))
    schema, _ = publication.schema_document(json.loads(compiled["bundle/schema-bundle.json"]))
    return schema


def assert_answer(actual, expected, observation, source_schema, binder_kind):
    schema = actual["schema"]
    l0.read_rows(schema, actual["rows"] + actual["undecided"])
    binder_prefix = f"{source_schema['pack']}@{l0.schema_id(source_schema)}:{binder_kind}/"

    def binder(id_):
        return {"$ref": binder_prefix + id_}

    rows = [
        {"$kind": "Answer", "$id": row["id"], "binder": binder(row["id"]), "c1": row["c1"]}
        for row in expected["rows"]
    ]
    witness = observation["witness"]
    undecided = [
        {"$kind": "Undecided", "$id": id_, "binder": binder(id_), "state": observation["state"],
         "reason": observation["reason"], "cause_relation": witness["relation"],
         "cause_key": json.dumps(witness["key"], separators=(",", ":"))}
        for id_ in expected["undecided"]
    ]
    assert {key: actual[key] for key in ("rows", "undecided", "counts")} == {
        "rows": rows, "undecided": undecided, "counts": expected["counts"],
    }


@pytest.mark.parametrize("case_id", ["value-ask-na-left-out", "value-value-invalid-blocks"])
def test_neutral_answer_case(case_id, neutral_schema):
    case = CORPUS["case_file"](case_id)
    inputs = case["input"]
    l0.read_rows(neutral_schema, inputs["rows"])
    run = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(DRIVER)],
        input=json.dumps({"schema": neutral_schema, "input": inputs}), capture_output=True,
        encoding="utf-8", timeout=30,
    )
    assert run.returncode == 0, run.stderr
    actual = json.loads(run.stdout)
    observation = case["expect"]
    expected = observation["value"].copy()
    question_schema, binder_kind = neutral_schema, "Item"
    if "fixture" in expected:
        fixture = actual["fixture"]
        fixture_expected = expected.pop("fixture")
        assert fixture["schema"]["kinds"]["Answer"]["slots"]["c1"]["type"] == fixture_expected["type"]
        assert_answer(fixture, fixture_expected, observation, neutral_schema, "Item")
        question_schema, binder_kind = fixture["schema"], "Answer"

    results = actual["results"]
    assert results.keys() == expected.keys()
    for name in inputs["questions"]:
        assert_answer(results[name], expected[name], observation, question_schema, binder_kind)
    for name in inputs.get("publication", {}):
        assert results[name] == expected[name]
