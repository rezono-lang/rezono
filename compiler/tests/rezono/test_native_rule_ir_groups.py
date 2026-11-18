"""Native group lowering against frozen signatures and independently checked witnesses."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler.rules import with_strata


RELATIONS = [
    {"name": "batch", "role": "base", "world": "closed", "key": [
        {"name": "zone", "type": "string"}, {"name": "band", "type": "string"}]},
    {"name": "entry", "role": "base", "world": "closed", "key": [
        {"name": "zone", "type": "string"}, {"name": "band", "type": "string"},
        {"name": "id", "type": "string"}, {"name": "amount", "type": "integer"}]},
    {"name": "tally", "role": "derived", "module": "measure", "explain": "materialize", "key": [
        {"name": "zone", "type": "string"}, {"name": "band", "type": "string"},
        {"name": "size", "type": "integer"}, {"name": "total", "type": "integer"}]},
    {"name": "peak", "role": "derived", "module": "measure", "explain": "materialize", "key": [
        {"name": "zone", "type": "string"}, {"name": "band", "type": "string"},
        {"name": "maximum", "type": "integer"}]},
]

ORIGINS = [{"file": "rezono/measure.rezono", "line": "5"}, {"file": "rezono/measure.rezono", "line": "8"}]
PROGRAM = {"format": "rezono.rules/1", "pack": "measurement", "relations": RELATIONS}

# Authored from sections 5 and 7 of decisions/language-native-rules.md. No reader or Datalog parser is used.
# rule tally(a, b, n, t) when batch(a, b) and n = entry(a, b, _, _).count() and t = entry(a, b, _, _).sum(it.amount)
# rule peak(a, b, m) when batch(a, b) and m = entry(a, b, _, _).max(it.amount)
CLAUSES = [
    {"rule": "tally", "args": [{"path": ["a"]}, {"path": ["b"]}, {"path": ["n"]}, {"path": ["t"]}],
     "when": {"and": [
         {"call": ["batch", [{"path": ["a"]}, {"path": ["b"]}]]},
         {"cmp": ["=", {"path": ["n"]}, {"agg": ["count", {"call": ["entry", [
             {"path": ["a"]}, {"path": ["b"]}, {"wildcard": True}, {"wildcard": True}]]}]}]},
         {"cmp": ["=", {"path": ["t"]}, {"agg": ["sum", {"call": ["entry", [
             {"path": ["a"]}, {"path": ["b"]}, {"wildcard": True}, {"wildcard": True}]]},
             {"path": ["it", "amount"]}]}]},
     ]}},
    {"rule": "peak", "args": [{"path": ["a"]}, {"path": ["b"]}, {"path": ["m"]}],
     "when": {"and": [
         {"call": ["batch", [{"path": ["a"]}, {"path": ["b"]}]]},
         {"cmp": ["=", {"path": ["m"]}, {"agg": ["max", {"call": ["entry", [
             {"path": ["a"]}, {"path": ["b"]}, {"wildcard": True}, {"wildcard": True}]]},
             {"path": ["it", "amount"]}]}]},
     ]}},
]

FROZEN_IR = {**PROGRAM, "rules": [
    {"id": "tally", "module": "measure", "stratum": "1", "origin": ORIGINS[0],
     "head": {"relation": "tally", "terms": ["?a", "?b", "?n", "?t"]},
     "body": [{"relation": "batch", "terms": ["?a", "?b"], "polarity": "positive", "stratum": "0"}],
     "aggregates": [
         {"relation": "entry", "terms": ["?a", "?b", "_", "_"], "function": "count", "as": "?n", "stratum": "0"},
         {"relation": "entry", "terms": ["?a", "?b", "_", "_"], "function": "sum", "as": "?t", "over": "amount", "stratum": "0"},
     ], "witness": {"relation": "tally__witness", "variables": ["?a", "?b", "?n", "?t"]}},
    {"id": "peak", "module": "measure", "stratum": "1", "origin": ORIGINS[1],
     "head": {"relation": "peak", "terms": ["?a", "?b", "?m"]},
     "body": [{"relation": "batch", "terms": ["?a", "?b"], "polarity": "positive", "stratum": "0"}],
     "aggregates": [
         {"relation": "entry", "terms": ["?a", "?b", "_", "_"], "function": "max", "as": "?m", "over": "amount", "stratum": "0"},
     ], "witness": {"relation": "peak__witness", "variables": ["?a", "?b", "?m"]}},
]}

TIED_ENTRIES = [["north", "early", "first", "7"], ["north", "early", "second", "7"]]
ROWS = {
    "batch": [["north", "early"], ["north", "quiet"]],
    "entry": [TIED_ENTRIES[1], ["south", "early", "fourth", "97"], TIED_ENTRIES[0], ["north", "late", "third", "98"]],
    "tally": [["north", "early", "2", "14"], ["north", "quiet", "0", "0"]],
    "peak": [["north", "early", "7"]],
}


def json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode("ascii")


def witness(rule, group, bindings, aggregates):
    return {
        "conclusion": {"relation": rule, "key": json_bytes([*group, *bindings.values()]).decode("ascii")},
        "rule_id": rule,
        "bindings": [{"variable": name, "value": value}
                     for name, value in {"?a": group[0], "?b": group[1], **bindings}.items()],
        "premises": [{"row": {"relation": "batch", "key": json_bytes(group).decode("ascii")},
                      "polarity": "positive", "stratum": 0}],
        "aggregates": aggregates,
    }


def evidence(position, group, contributors, result, *, measured=False):
    keys = [[json_bytes(row).decode("ascii"), f"known:{row[3]}"] if measured
            else [json_bytes(row).decode("ascii")] for row in sorted(contributors)]
    return {"relation": "entry", "position": position, "group_key": json_bytes(group).decode("ascii"),
            "count": len(keys), "contributors_sha256": sha256(json_bytes(keys)).hexdigest(), "result": result}


def check_groups(document):
    snapshots = {name: json_bytes([{"key": row} for row in rows]) for name, rows in ROWS.items()}
    manifest = {"id": "measured", "snapshots": [
        {"relation": name, "uri": name, "role": "all", "complete": True, "format": "json",
         "sha256": sha256(content).hexdigest()} for name, content in snapshots.items()]}
    rules = load_rules(document)

    def proof_report(step):
        proof = {"root": step["conclusion"], "manifest_id": "measured", "witnesses": [step]}
        return check(proof, manifest, rules, snapshots.__getitem__)

    group, empty = ["north", "early"], ["north", "quiet"]
    tally = witness("tally", group, {"?n": "2", "?t": "14"}, [
        evidence(0, group, TIED_ENTRIES, "known:2"), evidence(1, group, TIED_ENTRIES, "known:14", measured=True)])
    zero = witness("tally", empty, {"?n": "0", "?t": "0"}, [
        evidence(0, empty, [], "known:0"), evidence(1, empty, [], "known:0", measured=True)])
    tied_peak = witness("peak", group, {"?m": "7"}, [evidence(0, group, TIED_ENTRIES, "known:7", measured=True)])
    for step in (tally, zero, tied_peak):
        report = proof_report(step)
        assert report["valid"] and not report["findings"], report["findings"]

    wrong_group = deepcopy(tally)
    wrong_group["aggregates"][0]["group_key"] = '["north","quiet"]'
    wrong_position = deepcopy(tally)
    wrong_position["aggregates"][0]["position"] = 1
    missing_tied_entry = witness("peak", group, {"?m": "7"}, [
        evidence(0, group, TIED_ENTRIES[:1], "known:7", measured=True)])
    empty_peak = witness("peak", empty, {"?m": "0"}, [evidence(0, empty, [], "known:0", measured=True)])
    for step, expected in ((wrong_group, "aggregate_mismatch"), (wrong_position, "aggregate_mismatch"),
                           (missing_tied_entry, "aggregate_contributors"), (empty_peak, "aggregate_result")):
        report = proof_report(step)
        assert not report["valid"] and expected in {f["reason"] for f in report["findings"]}, report["findings"]


class NativeGroupLoweringMissing(ModuleNotFoundError):
    """The specific production entry point has yet to be implemented."""


def test_native_rule_ir_groups():
    check_groups(FROZEN_IR)
    try:
        from rezono_compiler.native_rule_groups import lower_group_clause
    except ModuleNotFoundError as error:
        if error.name != "rezono_compiler.native_rule_groups":
            raise
        raise NativeGroupLoweringMissing(error.name) from error
    lowered = [lower_group_clause(deepcopy(clause), deepcopy(RELATIONS), module="measure", origin=deepcopy(origin))
               for clause, origin in zip(CLAUSES, ORIGINS, strict=True)]
    actual = with_strata({**PROGRAM, "rules": lowered})
    assert actual == FROZEN_IR
    check_groups(actual)
