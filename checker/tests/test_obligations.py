"""AUD-C3: the checker holds an epoch's own obligations against the complete snapshots, not on the compiler's or
the publisher's word: an invariant relation is empty, and an outcome (W7) gives every element of its kind exactly
one state. Each witness below is a correct proof, so only the obligation itself can refuse the epoch."""

import hashlib
import json

import pytest

from rede_checker.canon import encode_key
from rede_checker.check import check_epoch
from rede_checker.rules import derived_relations, load_rules


def relation(name, role, *columns, **flags):
    return {"name": name, "role": role, "key": [{"name": c, "type": "string"} for c in columns], **flags}


def rule(rid, head, terms, body):
    return {"id": rid, "stratum": "0", "head": {"relation": head, "terms": terms},
            "body": [{"relation": r, "terms": ["?x"], "polarity": "positive", "stratum": "0"} for r in body]}


def epoch(relations, rules, rows):
    """Every row of every derived relation with its correct witness, checked as one complete epoch."""
    doc = {"format": "rede.rules/1", "relations": relations, "rules": rules}
    loaded = load_rules(doc)
    snaps = {r: json.dumps([{"key": k} for k in rs]).encode() for r, rs in rows.items()}
    manifest = {"id": "m-1", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                            "sha256": hashlib.sha256(b).hexdigest()} for r, b in snaps.items()]}
    witnesses = []
    for r in rules:
        for (x,) in rows[r["body"][0]["relation"]]:
            key = [x if t == "?x" else t for t in r["head"]["terms"]]
            if key in rows[r["head"]["relation"]]:
                witnesses.append({"conclusion": {"relation": r["head"]["relation"], "key": encode_key(key)},
                                  "rule_id": r["id"], "bindings": [{"variable": "?x", "value": x}],
                                  "premises": [{"row": {"relation": b["relation"], "key": encode_key([x])},
                                                "polarity": "positive", "stratum": 0} for b in r["body"]]})
    return check_epoch(witnesses, manifest, loaded, snaps.__getitem__, derived=derived_relations(doc, loaded))


def errors(report):
    return sorted((f["reason"], f.get("relation"), f.get("key")) for f in report["findings"] if f["severity"] == "error")


HOST = relation("host", "base", "id")
OWNED = relation("owned", "base", "id")


@pytest.mark.parametrize("invariant", [False, True])
def test_an_invariant_with_rows_blocks(invariant):
    relations = [HOST, relation("bad", "derived", "id", invariant=invariant)]
    report = epoch(relations, [rule("bad", "bad", ["?x"], ["host"])], {"host": [["h1"]], "bad": [["h1"]]})
    assert errors(report) == ([("invariant_violated", "bad", encode_key(["h1"]))] if invariant else [])


def test_an_empty_invariant_publishes():
    relations = [HOST, OWNED, relation("bad", "derived", "id", invariant=True)]
    report = epoch(relations, [rule("bad", "bad", ["?x"], ["owned"])], {"host": [["h1"]], "owned": [], "bad": []})
    assert report["valid"], report["findings"]


STATE = relation("state", "derived", "host", "state", "reason", outcome="host")
KNOWN = rule("state_known", "state", ["?x", "known", ""], ["owned"])


def test_a_complete_outcome_publishes():
    unknown = rule("state_unknown", "state", ["?x", "unknown", "not_recorded"], ["stray"])
    rows = {"host": [["h1"], ["h2"]], "owned": [["h1"]], "stray": [["h2"]],
            "state": [["h1", "known", ""], ["h2", "unknown", "not_recorded"]]}
    report = epoch([HOST, OWNED, relation("stray", "base", "id"), STATE], [KNOWN, unknown], rows)
    assert report["valid"], report["findings"]


def test_an_element_without_an_outcome_blocks():
    rows = {"host": [["h1"], ["h2"]], "owned": [["h1"]], "state": [["h1", "known", ""]]}
    report = epoch([HOST, OWNED, STATE], [KNOWN], rows)
    assert errors(report) == [("outcome_total", "state", encode_key(["h2"]))]


def test_an_outcome_for_no_element_blocks():
    rows = {"host": [["h1"]], "owned": [["h1"], ["ghost"]], "state": [["ghost", "known", ""], ["h1", "known", ""]]}
    report = epoch([HOST, OWNED, STATE], [KNOWN], rows)
    assert errors(report) == [("outcome_total", "state", encode_key(["ghost", "known", ""]))]


def test_two_states_for_one_element_block():
    unknown = rule("state_unknown", "state", ["?x", "unknown", "not_recorded"], ["host"])
    rows = {"host": [["h1"]], "owned": [["h1"]], "state": [["h1", "known", ""], ["h1", "unknown", "not_recorded"]]}
    report = epoch([HOST, OWNED, STATE], [KNOWN, unknown], rows)
    assert errors(report) == [("outcome_state", "state", encode_key(["h1"]))]


def test_several_reasons_for_unknown_publish():
    a = rule("state_a", "state", ["?x", "unknown", "no_owner"], ["host"])
    b = rule("state_b", "state", ["?x", "unknown", "no_place"], ["host"])
    rows = {"host": [["h1"]], "state": [["h1", "unknown", "no_owner"], ["h1", "unknown", "no_place"]]}
    report = epoch([HOST, STATE], [a, b], rows)
    assert report["valid"], report["findings"]


def test_an_outcome_over_no_kind_is_refused():
    """Review of #465: an outcome that names an empty derived relation would make totality vacuous."""
    decoy = relation("decoy", "derived", "id")
    for target in ("decoy", "owned_pair", "missing"):
        state = {**STATE, "outcome": target}
        pair = relation("owned_pair", "base", "id", "other")
        with pytest.raises(ValueError, match="is not a kind"):
            epoch([HOST, OWNED, decoy, pair, state], [KNOWN, rule("decoy", "decoy", ["?x"], ["owned"])],
                  {"host": [["h1"]], "owned": [], "decoy": [], "owned_pair": [], "state": []})
    typed = {**HOST, "key": [{"name": "id", "type": "integer"}]}
    with pytest.raises(ValueError, match="is not a kind"):
        epoch([typed, OWNED, STATE], [KNOWN], {"host": [["1"]], "owned": [], "state": []})


def test_an_outcome_row_without_three_parts_is_a_finding_not_a_crash():
    """Review of #465: a row {"key": []} is reported before any part of it is read."""
    rows = {"host": [["h1"]], "owned": [["h1"]], "state": [[], ["h1", "known", ""]]}
    report = epoch([HOST, OWNED, STATE], [KNOWN], rows)
    assert errors(report) == [("outcome_state", "state", encode_key([])), ("unproven_row", "state", encode_key([]))]


@pytest.mark.parametrize("state, reason", [("known", "late"), ("unknown", ""), ("invalid", "broken"),
                                           ("unknown", "Not Recorded")])
def test_a_state_or_reason_outside_w7_blocks(state, reason):
    odd = rule("state_odd", "state", ["?x", state, reason], ["host"])
    rows = {"host": [["h1"]], "state": [["h1", state, reason]]}
    report = epoch([HOST, STATE], [odd], rows)
    assert errors(report) == [("outcome_state", "state", encode_key(["h1"]))]
