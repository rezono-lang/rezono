"""Prepare an ordinary pack replay for the Python conformance tests."""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import json

import jsonschema
import pytest
import yaml

from rezono_canon import canonical_sha256, sha256_hex
from rezono_compiler import batch, emit, explain, facts, modules, pack, rules
from rezono_publication import l0, publication


DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
NEUTRAL = ROOT / "tests/fixtures/neutral"


@dataclass(frozen=True)
class Replay:
    rules: dict
    rows: dict[str, set[tuple[str, ...]]]
    witnesses: list[dict]
    snapshots: dict[str, bytes]
    publication_schema: dict
    publication_plan: dict


def case_file(case_id):
    path = DIRECTORY / f"{case_id}.yaml"
    schema = jsonschema.Draft202012Validator(json.loads((DIRECTORY / "case.schema.json").read_text("utf-8")))
    case = yaml.safe_load(path.read_text("utf-8"))
    schema.validate(case)
    assert case_id == case["id"]
    return case


def cases(engine):
    runnable = []
    for path in sorted(DIRECTORY.glob("*.yaml")):
        if path.name != "sources.yaml":
            case = case_file(path.stem)
            payload = case["input"]
            if "rules" not in payload:
                continue
            assert "select" in payload, f"{case['id']}: a rule replay needs its selected subject"
            reason = case.get("unsupported", {}).get(engine)
            runnable.append(pytest.param(case, id=case["id"], marks=pytest.mark.skip(reason=reason)) if reason
                            else pytest.param(case, id=case["id"]))
    assert any(not parameter.marks for parameter in runnable), f"{engine} has no runnable neutral cases"
    return runnable


def decode(value, slot):
    if isinstance(value, list):
        return [decode(member, slot) for member in value]
    if isinstance(value, dict) and value.keys() == {"$ref"}:
        return value["$ref"]
    return int(value) if slot.sql_type == "BIGINT" else value


def play(case, directory):
    model_dir = modules.copy_closure(NEUTRAL, directory / "pack")
    compiled = case["input"]["rules"]
    (model_dir / "rules/case.dl").write_bytes(compiled["clauses"].encode("utf-8"))
    model = pack.read(model_dir)
    program = rules.load(model.rules)
    outputs = emit.compile_pack(model)
    schema, plan = publication.schema_document(json.loads(outputs["bundle/schema-bundle.json"]))
    admitted = l0.read_rows(schema, case["input"]["rows"])
    records = defaultdict(list)
    for row in admitted:
        kind = pack.snake(row["$kind"])
        slots = {slot.name: slot for slot in model.all_slots(kind)}
        records[kind].append({
            "id": row["$id"],
            **{name: decode(value, slots[name]) for name, value in row.items() if not name.startswith("$")},
        })
    with closing(batch.connect(program, facts.rows_of(model, records), threads=1)) as database:
        batch.compute(database, program)
        rows = batch.read(database, program, program.base_used() + program.derived())
        proof = explain.Explainer(program, rows, batch.witnesses(database, program))
        snapshots = {name: proof.snapshot(name).encode("utf-8") for name in rows}
        return Replay(model.rules, rows, proof.chosen(), snapshots, schema, plan)


def manifest(case, snapshots):
    return {"id": case["id"], "snapshots": [
        {"relation": name, "role": "all", "complete": True, "uri": name, "format": "json", "sha256": sha256_hex(raw)}
        for name, raw in snapshots.items()
    ]}


def read_sum(case, rows, witnesses):
    selection = case["input"]["select"]
    subject = selection["id"]
    relation = case["input"]["rules"]["output"]
    (value,) = [row[1] for row in rows[relation] if row[0] == subject]
    (root,) = [w for w in witnesses if w["conclusion"] == {"relation": relation, "key": explain.key_text([subject, value])}]
    (aggregate,) = root["aggregates"]
    assert aggregate["group_key"] == explain.key_text([subject])
    assert root["premises"] == [{"row": {"relation": pack.snake(selection["kind"]), "key": aggregate["group_key"]},
                                 "polarity": "positive", "stratum": 0}]
    members = sorted([row for row in rows[aggregate["relation"]] if row[0] == subject])
    contributors = [[explain.key_text(row), f"known:{row[-1]}"] for row in members]
    assert aggregate["count"] == len(contributors)
    assert aggregate["contributors_sha256"] == canonical_sha256(contributors)
    state, _, result = aggregate["result"].partition(":")
    assert result == value
    return {"value": value, "state": state, "reason": None, "witness": {
        "subject": selection, "members": [row[1] for row in members],
    }}
