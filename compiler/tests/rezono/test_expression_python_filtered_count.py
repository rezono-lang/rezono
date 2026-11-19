"""Lower the shared fixed-key filter and replay its actual group witnesses."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
import yaml

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import diagnostics, rules_dl
from rezono_compiler.native_rule_groups import lower_group_clause
from rezono_compiler.rules import with_strata

from test_native_rule_ir_groups import evidence, json_bytes, witness


CORPUS = Path(__file__).resolve().parents[3] / "tests/conformance"
ORIGIN = {"file": "rezono/measure.rezono", "line": "3"}


class MissingFilteredCountDiagnostic(AssertionError):
    """The unsupported filter is currently refused without R044."""


def replay_groups(case, lowered):
    native = case["input"]["native_filter"]
    expected = case["expect"]
    rows = {relation["name"]: [] for relation in native["relations"]}
    for record in case["input"]["rows"]:
        rows[record["relation"]].append(record["key"])
    rows["tally"] = expected["value"]["rows"]
    snapshots = {name: json_bytes([{"key": row} for row in values]) for name, values in rows.items()}
    manifest = {"id": "filtered", "snapshots": [
        {"relation": name, "uri": name, "role": "all", "complete": True, "format": "json",
         "sha256": sha256(content).hexdigest()}
        for name, content in snapshots.items()
    ]}
    program = load_rules(lowered)

    def report(instance):
        proof = {"root": instance["conclusion"], "manifest_id": "filtered", "witnesses": [instance]}
        return check(proof, manifest, program, snapshots.__getitem__)

    for row, group in zip(rows["tally"], expected["witness"], strict=True):
        key, contributors = group["group"], group["contributors"]
        count = row[2]
        instance = witness("tally", key, {"?n": count}, [
            evidence(0, key, contributors, f"known:{count}"),
        ])
        checked = report(instance)
        assert checked["valid"] and not checked["findings"], checked["findings"]
        if contributors:
            instance["aggregates"][0] = evidence(0, key, contributors[:1], f"known:{count}")
            forged = report(instance)
            assert not forged["valid"]
            assert "aggregate_contributors" in {item["reason"] for item in forged["findings"]}


def test_expression_python_filtered_count():
    case = yaml.safe_load((CORPUS / "expression-filtered-count.yaml").read_bytes())
    schema = json.loads((CORPUS / "case.schema.json").read_bytes())
    Draft202012Validator(schema).validate(case)
    assert case["id"] == "expression-filtered-count"
    native = case["input"]["native_filter"]

    def lower(clause):
        return lower_group_clause(clause, deepcopy(native["relations"]), module="measure", origin=ORIGIN)

    program = with_strata({"format": "rezono.rules/1", "pack": "measurement",
                           "relations": deepcopy(native["relations"]),
                           "rules": [lower(deepcopy(native["declaration"]))]})
    [rule] = program["rules"]
    assert rule["aggregates"] == case["expect"]["value"]["aggregates"]
    replay_groups(case, program)

    unsupported = deepcopy(native["declaration"])
    filter_ = unsupported["when"]["and"][1]["cmp"][2]["agg"][1]["filter"]
    filter_[1]["and"][1]["cmp"] = native["unrepresentable"]["comparison"]
    with pytest.raises((rules_dl.RuleError, diagnostics.Diagnosed)) as refused:
        lower(unsupported)
    error = refused.value
    found = [diagnostic.code for diagnostic in getattr(error, "diagnostics", ())]
    if not found and str(error) == "rezono/measure.rezono:3: an aggregate filter must fix a ranged key column by equality":
        raise MissingFilteredCountDiagnostic(str(error))
    assert found == [native["unrepresentable"]["code"]], str(error)
