"""AUD-C1: an evaluated `invalid` calculation result blocks the publication (values.md §3.3, owner on #350:
`invalid` means the model contradicts itself, which is ours to fix). The proof of it stays in the report."""

import hashlib
import json

from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import load_rules

DATE = "2026-11-01"
REASON = "division by zero in ratio"
RULES = {"format": "rezono.rules/1", "relations": [], "rules": []}
CALC = {
    "subject": "Entry", "subject_table": "entry", "as_of": "calc__as_of",
    "facts": [{"id": "total", "type": "number", "reads": "column", "table": "entry_total", "index": 1}],
    "rules": [{"rule": "share", "view": "calc__share", "type": "number", "versions": ["share@v1"]}],
}


def calculation(denominator: int) -> dict:
    value = {"op": "ratio", "args": [{"fact": "total"}, {"integer": 1}, {"integer": denominator}]}
    return {**CALC, "versions": [{"id": "share@v1", "version": "v1", "view": "calc__share__v1", "rule": "share",
                                  "valid_from": DATE, "valid_until": "2026-12-01", "known_from": DATE,
                                  "definitions": [{"name": "share", "when": {"boolean": True}, "value": value}]}]}


def epoch(denominator: int, state: str, value: str, reason: str) -> dict:
    """A correct witness of ratio(14, 1, denominator) and the snapshots it is checked against."""
    key = ["e1", value, state, reason]
    rows = {"entry": [["e1"]], "entry_total": [["e1", "14"]], "calc__as_of": [["as_of", DATE, DATE]],
            "calc__share": [key]}
    snaps = {r: json.dumps([{"key": k} for k in rs]).encode() for r, rs in rows.items()}
    manifest = {"id": "m-1", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                            "sha256": hashlib.sha256(b).hexdigest()} for r, b in snaps.items()]}
    witness = {"conclusion": {"relation": "calc__share", "key": encode_key(key)}, "rule": "share", "version": "v1",
               "definition": "share", "valid_at": DATE, "known_at": DATE, "state": state, "value": value,
               "reason": reason, "reads": ["calc__as_of", "entry_total"],
               "premises": [{"relation": "entry_total", "key": encode_key(["e1", "14"])}],
               "steps": [{"path": "share/value", "op": "ratio", "state": state, "value": value, "reason": reason},
                         {"path": "share/value/0", "op": "fact", "ref": "total", "relation": "entry_total",
                          "state": "known", "value": "14"}]}
    return check_epoch([], manifest, load_rules(RULES), snaps.__getitem__, derived=set(),
                       calc_witnesses=[witness], calc_ir=calculation(denominator))


def errors(report: dict) -> list:
    return [f for f in report["findings"] if f["severity"] == "error"]


def test_a_known_result_publishes():
    report = epoch(2, "known", "7", "")
    assert report["valid"], report["findings"]


def test_a_correctly_proven_invalid_result_blocks_and_keeps_its_proof():
    report = epoch(0, "invalid", "", REASON)
    assert not report["valid"]
    assert errors(report) == [{"reason": "calc_invalid", "severity": "error", "witness": 0, "relation": "calc__share",
                               "key": encode_key(["e1", "", "invalid", REASON]), "detail": REASON}]


def test_a_witness_that_hides_an_invalid_result_still_blocks():
    """Claiming `known` where the operator gives `invalid` is a wrong step: it blocks too."""
    report = epoch(0, "known", "0", "")
    assert not report["valid"] and "calc_step" in {f["reason"] for f in errors(report)}
