"""An independent certificate must bind both snapshots and their safety obligations."""

from copy import deepcopy
from importlib.util import find_spec

import pytest

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_checker.check import check_epoch
from rezono_checker.rules import load_rules


def relation(name, role, *columns, **properties):
    return {"name": name, "role": role, "key": [{"name": col, "type": "string"} for col in columns], **properties}


def literal(relation, *terms, polarity="positive"):
    return {"relation": relation, "terms": list(terms), "polarity": polarity, "stratum": "0"}


def rule(name, level, terms, *body):
    return {"id": name, "stratum": str(level), "head": {"relation": name, "terms": terms}, "body": list(body)}


PROGRAM = {
    "format": "rezono.rules/1",
    "relations": [
        relation("link__tail", "base", "link", "item"),
        relation("allowed", "base", "item"),
        relation("labelled", "base", "link"),
        relation("outgoing", "derived", "item", "link"),
        relation("blocked_tail", "derived", "link", "item", invariant=True),
        relation("unlabelled_link", "derived", "link", "item", invariant=True),
    ],
    "rules": [
        rule("outgoing", 0, ["?i", "?l"], literal("link__tail", "?l", "?i")),
        rule("blocked_tail", 1, ["?l", "?i"], literal("link__tail", "?l", "?i"),
             literal("allowed", "?i", polarity="negative")),
        rule("unlabelled_link", 1, ["?l", "?i"], literal("link__tail", "?l", "?i"),
             literal("labelled", "?l", polarity="negative")),
    ],
}
INVARIANTS = ("blocked_tail", "unlabelled_link")
OLD = ("link-a", "item-a")
NEW = ("link-a", "item-b")
DELTA = [("link__tail", OLD, -1), ("link__tail", NEW, 1)]
OBSERVATIONS = {"observation-a": b'{"id":"observation-a","scope":"links","run":"run-a"}'}
CUT = {"run": "run-a", "scope": "links", "id": "cut-a", "observation_sha256": sha256_hex(OBSERVATIONS["observation-a"])}


def row_ref(name, row):
    return {"relation": name, "key": canonical_json(list(row))}


def snapshot(id_, tail):
    link, item = tail
    witness = {
        "rule_id": "outgoing", "conclusion": row_ref("outgoing", (item, link)),
        "bindings": [{"variable": "?i", "value": item}, {"variable": "?l", "value": link}],
        "premises": [{"row": row_ref("link__tail", tail), "polarity": "positive", "stratum": 0}],
    }
    rows = {
        "link__tail": [tail], "outgoing": [(item, link)],
        "allowed": [("item-a",), ("item-b",)], "labelled": [("link-a",)],
        "blocked_tail": [], "unlabelled_link": [],
    }
    return {"id": id_, "rows": rows, "witnesses": [witness]}


def ordinary_check(state):
    files = {name: canonical_bytes([{"key": list(key)} for key in keys]) for name, keys in state["rows"].items()}
    manifest = {"id": state["id"], "snapshots": [
        {"relation": name, "role": "all", "format": "json", "uri": name, "complete": True, "sha256": sha256_hex(body)}
        for name, body in files.items()
    ]}
    return check_epoch(state["witnesses"], manifest, load_rules(PROGRAM), files.__getitem__,
                       derived={"outgoing", *INVARIANTS})


def test_transition_certificate():
    base = snapshot("base", OLD)
    variant = snapshot("variant", NEW)
    context = {"manifest": "desired-a", "cut": CUT, "definition_sha256": canonical_sha256(PROGRAM),
               "observations": OBSERVATIONS, "program": PROGRAM, "invariants": INVARIANTS}
    certificate = {
        "manifest": context["manifest"], "run": CUT["run"], "cut": CUT["id"],
        "definition_sha256": context["definition_sha256"],
        "base": canonical_sha256(base), "variant": canonical_sha256(variant),
        "rule": "replace_tail", "bindings": {"link": "link-a"},
        "effect": "replace-link-a", "expected_old": [row_ref("link__tail", OLD)], "delta": DELTA,
        "invariants": dict.fromkeys(INVARIANTS, {"rows": [], "count": "0"}),
    }
    forged_variant = deepcopy(variant)
    # The claimed zero is now false even though the ordinary added conclusion still has a witness.
    forged_variant["rows"]["allowed"] = [("item-a",)]
    if not all(ordinary_check(state)["valid"] for state in (base, variant)):
        pytest.fail("The independently authored ordinary witnesses are not valid.")
    if ordinary_check(forged_variant)["valid"]:
        pytest.fail("The ordinary checker missed the deliberately missing invariant row.")

    assert find_spec("rezono_checker.transition"), "the independent checker has no transition certificate verification"
    from rezono_checker.transition import check_transition_certificate

    accepted = check_transition_certificate(certificate, context, base, variant)
    assert accepted["valid"] and not accepted["findings"]
    for changed, target in (
        (certificate | {"invariants": {"blocked_tail": certificate["invariants"]["blocked_tail"]}}, variant),
        (certificate | {"variant": canonical_sha256(forged_variant)}, forged_variant),
        (certificate | {"cut": "cut-b"}, variant),
        (certificate | {"delta": [DELTA[0], ("link__tail", ("link-a", "item-c"), 1)]}, variant),
    ):
        refused = check_transition_certificate(changed, context, base, target)
        assert not refused["valid"] and refused["findings"]
