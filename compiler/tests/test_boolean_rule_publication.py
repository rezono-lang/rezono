"""A boolean rule column reaches the checker as canonical true/false text (decisions/boolean-rule-inputs.md)."""

import json
import shutil
from hashlib import sha256

import pytest
import yaml

from rezono_checker import transition
from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, emit, explain, facts, pack, rules
from support import FIXTURE


SOURCE = """
.decl observed_flag(item: symbol, value: boolean)
observed_flag(item, value) :- alpha(item), alpha__flag(item, value).
.decl confirmed(item: symbol)
confirmed(item) :- observed_flag(item, value), value = TRUE.
.decl incomplete(item: symbol)
incomplete(item) :- observed_flag(item, value), value = FALSE.
"""


@pytest.fixture
def boolean_pack(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    schema = folder / "schema/minimal.yaml"
    document = yaml.safe_load(schema.read_bytes())
    document["classes"]["Alpha"]["attributes"]["flag"] = {"range": "boolean"}
    schema.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (folder / "rules").mkdir()
    (folder / "rules/observation.dl").write_text(SOURCE, encoding="utf-8")
    return folder


def manifest(snapshots):
    return {"id": "m-1", "snapshots": [
        {"relation": name, "role": "all", "complete": True, "uri": name, "format": "json",
         "sha256": sha256(data).hexdigest()}
        for name, data in sorted(snapshots.items())
    ]}


def test_boolean_publication_round_trips_through_checker(boolean_pack):
    model = pack.read(boolean_pack)
    doc = json.loads(emit.compile_pack(model)["ir/rules.json"])
    program = rules.load(doc)
    rows = facts.rows_of(model, {"alpha": [{"id": "a", "title": "one", "flag": True},
                                           {"id": "b", "title": "two", "flag": False},
                                           {"id": "c", "title": "three"}]})
    with batch.connect(program, rows) as connection:
        batch.compute(connection, program, witnesses=True)
        derived = batch.read(connection, program)
        data = batch.read(connection, program, program.base_used()) | derived
        found = batch.witnesses(connection, program)
        explainer = explain.Explainer(program, data, found)
    assert derived["observed_flag"] == {("a", "true"), ("b", "false")}
    assert data["alpha__flag"] == {("a", "true"), ("b", "false")}
    assert {value for theta in found.values() for row in theta for value in row} <= {"a", "b", "true", "false"}

    snapshots = {name: explainer.snapshot(name).encode() for name in data}
    checked = load_rules(doc)
    for relation, key in (("confirmed", ("a",)), ("incomplete", ("b",)),
                          ("observed_flag", ("a", "true")), ("observed_flag", ("b", "false"))):
        proof = explainer.proof(relation, key, "m-1")
        report = check(proof, manifest(snapshots), checked, snapshots.__getitem__)
        assert report["valid"] and not report["findings"], (relation, key, report)

    catalogue = transition._catalogue(doc)
    assert catalogue["observed_flag"].columns[1] == "boolean"
    assert transition._key(["a", "true"], catalogue["observed_flag"]) == ("a", "true")
    for spelling in ("True", "FALSE", "1"):
        with pytest.raises(transition.Refused, match="malformed_row_key"):
            transition._key(["a", spelling], catalogue["observed_flag"])
