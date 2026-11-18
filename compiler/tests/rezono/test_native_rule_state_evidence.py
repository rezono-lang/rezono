"""Freeze state evidence independently of the native reader and both rule engines.

The exposed relation can support a state test only when its row agrees with
the archived Value and origin. Lowering must report R047 when it has no such
evidence, including an omission without a separate absence proof or a withheld
value. A known-only selection can still prove a positive known result.

The mixed fold of known 7 and n/a in the language decision remains unresolved.
This task makes no direct stateful aggregate eligible for lowering.
"""

import json

import pytest

from rezono_canon import sha256_hex
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import derived_relations, load_rules


VALUE_SOURCE = "item_values"
STATE_PROJECTION = "item__estimate_state"
CONCLUSION = "observed_state"
METADATA = "ir/state-projections.json"

# The input is authored independently of the engine's projection. The missing
# required estimate has a subject and a trace, but no Value or absence proof.
AUTHORED = [
    {"key": ["measured"], "values": {
        "estimate": {"state": "known", "value": "7"},
        "origin": {"state": "known", "value": "inputs/measurements.json#/0/estimate"},
    }},
    {"key": ["unmeasured"], "values": {
        "estimate": {"state": "unknown", "reason": "not_measured"},
        "origin": {"state": "known", "value": "inputs/measurements.json#/1/estimate"},
    }},
    {"key": ["irrelevant"], "values": {
        "estimate": {"state": "not_applicable", "reason": "not_required_here"},
        "origin": {"state": "known", "value": "inputs/measurements.json#/2/estimate"},
    }},
    {"key": ["inconsistent"], "values": {
        "estimate": {"state": "invalid", "reason": "out_of_range"},
        "origin": {"state": "known", "value": "inputs/measurements.json#/3/estimate"},
    }},
    {"key": ["missing-required"], "values": {
        "origin": {"state": "known", "value": "inputs/measurements.json#/4"},
    }},
    {"key": ["withheld"], "values": {
        "estimate": {"state": "known", "value": "19"},
        "origin": {"state": "known", "value": "inputs/measurements.json#/5/estimate"},
    }},
]
EXPECTED = [
    ("measured", "known", "", "inputs/measurements.json#/0/estimate"),
    ("unmeasured", "unknown", "not_measured", "inputs/measurements.json#/1/estimate"),
    ("irrelevant", "not_applicable", "not_required_here", "inputs/measurements.json#/2/estimate"),
    ("inconsistent", "invalid", "out_of_range", "inputs/measurements.json#/3/estimate"),
    ("withheld", "known", "", "inputs/measurements.json#/5/estimate"),
]


def relation(name, role, *columns):
    return {"name": name, "role": role, "key": [{"name": c, "type": "string"} for c in columns]}


TERMS = ["?subject", "?state", "?reason"]
IR = {
    "format": "rezono.rules/1",
    "pack": "state-evidence",
    "relations": [
        relation(VALUE_SOURCE, "base", "subject"),
        relation(STATE_PROJECTION, "base", "subject", "state", "reason"),
        relation(CONCLUSION, "derived", "subject", "state", "reason"),
    ],
    "rules": [{
        "id": CONCLUSION, "stratum": "0",
        "head": {"relation": CONCLUSION, "terms": TERMS},
        "body": [{"relation": STATE_PROJECTION, "terms": TERMS, "polarity": "positive", "stratum": "0"}],
    }],
}


def check_epoch_with_states(projected, *, role=None, source_withheld=False, bad_metadata_hash=False):
    """Build a consistent engine claim without touching the authored evidence."""
    claimed = [{"key": [subject, state, reason],
                "values": {"origin": {"state": "known", "value": origin}}}
               for subject, state, reason, origin in projected]
    authored = AUTHORED if role is None else AUTHORED[:1]
    snapshots = {VALUE_SOURCE: authored, STATE_PROJECTION: claimed,
                 CONCLUSION: [{"key": row["key"]} for row in claimed]}
    files = {name: json.dumps(rows).encode("utf-8") for name, rows in snapshots.items()}
    # Archived projection metadata links the IR relation to a Value column and
    # its independently captured origin. It is data, never an executable adapter.
    files[METADATA] = json.dumps([{
        "relation": STATE_PROJECTION, "source_relation": VALUE_SOURCE,
        "value_column": "estimate", "origin_column": "origin", "required": True,
    }]).encode("utf-8")
    manifest = {
        "id": "m-1",
        "compiled": [{"file": METADATA, "uri": METADATA,
                      "sha256": "0" * 64 if bad_metadata_hash else sha256_hex(files[METADATA])}],
        "snapshots": [
            {"relation": name, "role": role or "all", "complete": not source_withheld or name != VALUE_SOURCE,
             "uri": name, "format": "json", "sha256": sha256_hex(files[name])}
            for name in snapshots
        ],
    }
    witnesses = []
    for row in claimed:
        key = encode_key(row["key"])
        witnesses.append({
            "rule_id": CONCLUSION,
            "conclusion": {"relation": CONCLUSION, "key": key},
            "bindings": [{"variable": term, "value": value} for term, value in zip(TERMS, row["key"], strict=True)],
            "premises": [{"row": {"relation": STATE_PROJECTION, "key": key},
                          "polarity": "positive", "stratum": 0}],
        })
    rules = load_rules(IR)
    full = {s["relation"] for s in manifest["snapshots"] if s["complete"]} if role is not None else None
    return check_epoch(witnesses, manifest, rules, files.__getitem__, derived=derived_relations(IR, rules), full=full)


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Read decisions/language-native-rules.md, lowering, diagnostics and open points. "
           "In checker/rezono_checker, authenticate archived state projections against the authored Value and origin "
           "through check_epoch. Refuse unsupported omission and role-withheld evidence. "
           "The hand-authored snapshots and IR do not need a native parser.",
)
def test_native_rule_state_evidence():
    genuine = check_epoch_with_states(EXPECTED)
    assert genuine["valid"], genuine["findings"]
    genuine_role = check_epoch_with_states(EXPECTED[:1], role="reader")
    assert genuine_role["valid"], genuine_role["findings"]

    cases = {
        "forged state": check_epoch_with_states([
            EXPECTED[0], ("unmeasured", "known", "", EXPECTED[1][3]), *EXPECTED[2:],
        ]),
        "forged reason": check_epoch_with_states([
            EXPECTED[0], ("unmeasured", "unknown", "wrong_reason", EXPECTED[1][3]), *EXPECTED[2:],
        ]),
        "unrelated origin": check_epoch_with_states([
            EXPECTED[0], ("unmeasured", "unknown", "not_measured", EXPECTED[0][3]), *EXPECTED[2:],
        ]),
        "unsupported absence": check_epoch_with_states([
            *EXPECTED, ("missing-required", "unknown", "no_value", "inputs/measurements.json#/4"),
        ]),
        "withheld value": check_epoch_with_states([
            *EXPECTED[:1], ("withheld", "unknown", "withheld", "inputs/measurements.json#/5/estimate"),
        ], role="reader", source_withheld=True),
        "unverified metadata": check_epoch_with_states(EXPECTED, bad_metadata_hash=True),
    }
    accepted = [name for name, result in cases.items() if result["valid"]]
    assert not accepted, f"checker accepted unsupported state claims: {', '.join(accepted)}"
