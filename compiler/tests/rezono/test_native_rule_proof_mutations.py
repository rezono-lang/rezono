"""Independently authored IR and witnesses for language-native-rules.md, sections 4, 5 and 11."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from rezono_checker.check import check, check_epoch
from rezono_checker.rules import derived_relations, load_rules


def key(*parts):
    return json.dumps(parts, separators=(",", ":"))


def premise(relation, *terms, stratum=0, polarity="positive"):
    return {"relation": relation, "terms": list(terms), "stratum": str(stratum), "polarity": polarity}


def rule(rule_id, head, terms, body, variables, *, stratum=0, **expressions):
    return {"id": rule_id, "module": "proof", "stratum": str(stratum),
            "head": {"relation": head, "terms": list(terms)}, "body": body,
            "origin": {"file": "rules/proof.rezono", "line": "3"},
            "witness": {"relation": f"{rule_id}__witness", "variables": sorted(variables.split())},
            **expressions}


def program(definitions, **columns):
    derived = {r["head"]["relation"] for r in definitions}
    relations = [
        {"name": name, "role": "derived" if name in derived else "base", "world": "closed",
         "key": [{"name": label.removesuffix(":int"), "type": "integer" if label.endswith(":int") else "string"}
                 for label in labels.split()]}
        for name, labels in sorted(columns.items())
    ]
    return {"format": "rezono.rules/1", "pack": "proof", "relations": relations,
            "rules": sorted(definitions, key=lambda r: r["id"])}


def evidence(relation, row, stratum=0, polarity="positive"):
    return {"row": {"relation": relation, "key": key(*row)}, "stratum": stratum, "polarity": polarity}


def witness(rule_id, relation, row, bindings, *premises, aggregates=None):
    result = {"rule_id": rule_id, "conclusion": {"relation": relation, "key": key(*row)},
              "bindings": [{"variable": "?" + var, "value": value} for var, value in sorted(bindings.items())],
              "premises": list(premises)}
    if aggregates is not None:
        result["aggregates"] = aggregates
    return result


def count_domain(relation, terms, bind, stratum=0):
    return {"relation": relation, "terms": list(terms), "function": "count", "as": bind, "stratum": str(stratum)}


def counted(relation, position, group, members):
    # Each listed key is an independent expected contributor. The checker finds its own members.
    encoded = key(*([member] for member in sorted(key(*row) for row in members))).encode()
    return {"relation": relation, "position": position, "group_key": key(*group),
            "count": len(members), "contributors_sha256": sha256(encoded).hexdigest(),
            "result": f"known:{len(members)}"}


def snapshots(rows, *, filtered=()):
    files = {name: json.dumps([{"key": row} for row in values]).encode() for name, values in rows.items()}
    manifest = {"id": "epoch", "snapshots": [
        {"relation": name, "role": "reader" if name in filtered else "checker",
         "complete": name not in filtered, "format": "json", "uri": name, "sha256": sha256(data).hexdigest()}
        for name, data in files.items()
    ]}
    return manifest, files.__getitem__


def epoch(doc, rows, witnesses):
    manifest, read = snapshots(rows)
    rules = load_rules(doc)
    return check_epoch(witnesses, manifest, rules, read, derived=derived_relations(doc, rules))


def proof(doc, rows, witnesses, *, filtered=()):
    manifest, read = snapshots(rows, filtered=filtered)
    return check({"manifest_id": "epoch", "root": witnesses[0]["conclusion"], "witnesses": witnesses},
                 manifest, load_rules(doc), read)


def scoped_sweep():
    scope = ("r", "collector", "sweep")
    certificate = (*scope, "coverage")
    absent = (*scope, "sensor")
    doc = program([
        rule("complete_sweep", "complete_sweep", ("?run", "?scope", "?sweep", "?cover"), [
            premise("verified_sweep", "?run", "?scope", "?sweep", "?cover"),
        ], "?run ?scope ?sweep ?cover"),
        rule("absent", "absent", ("?run", "?scope", "?sweep", "?item"), [
            premise("expected", "?run", "?scope", "?sweep", "?item"),
            premise("complete_sweep", "?run", "?scope", "?sweep", "?cover"),
            premise("present", "?run", "?scope", "?sweep", "?item", polarity="negative"),
        ], "?run ?scope ?sweep ?item ?cover", stratum=1),
    ], verified_sweep="run scope sweep coverage", complete_sweep="run scope sweep coverage",
        expected="run scope sweep item", present="run scope sweep item", absent="run scope sweep item")
    rows = {"expected": [absent], "verified_sweep": [certificate], "complete_sweep": [certificate],
            "present": [("r", "another_collector", "sweep", "sensor")], "absent": [absent]}
    complete = witness("complete_sweep", "complete_sweep", certificate,
                       dict(run="r", scope="collector", sweep="sweep", cover="coverage"),
                       evidence("verified_sweep", certificate))
    claim = witness("absent", "absent", absent,
                    dict(run="r", scope="collector", sweep="sweep", item="sensor", cover="coverage"),
                    evidence("expected", absent), evidence("complete_sweep", certificate),
                    evidence("present", absent, polarity="negative"))
    return doc, rows, [claim, complete]


def tied_offers():
    doc = program([
        rule("eligible", "eligible", ("?d", "?o", "?total", "?rank"), [
            premise("priced", "?d", "?o", "?total", "?rank"),
        ], "?d ?o ?total ?rank"),
        rule("eligible_offer", "eligible_offer", ("?d", "?o"), [
            premise("eligible", "?d", "?o", "?total", "?rank"),
        ], "?d ?o ?total ?rank"),
        rule("comparison_1", "comparison", ("?d", "?o", "?o", "?total", "?rank"), [
            premise("eligible", "?d", "?o", "?total", "?rank"),
        ], "?d ?o ?total ?rank"),
        rule("comparison_2", "comparison", ("?d", "?o", "?other", "?higher", "?later"), [
            premise("eligible", "?d", "?o", "?total", "?rank"),
            premise("eligible", "?d", "?other", "?higher", "?later"),
        ], "?d ?o ?other ?total ?rank ?higher ?later",
            conditions=[{"left": "?total", "op": "lt", "right": "?higher"}]),
        rule("comparison_3", "comparison", ("?d", "?o", "?other", "?total", "?later"), [
            premise("eligible", "?d", "?o", "?total", "?rank"),
            premise("eligible", "?d", "?other", "?total", "?later"),
        ], "?d ?o ?other ?total ?rank ?later", conditions=[{"left": "?rank", "op": "lt", "right": "?later"}]),
        rule("excluded", "excluded", ("?d", "?o"), [
            premise("demand", "?d"), premise("offer", "?o"),
            premise("eligible_offer", "?d", "?o", polarity="negative"),
        ], "?d ?o", stratum=1),
        rule("selected", "selected", ("?d", "?o"), [
            premise("eligible", "?d", "?o", "?anon_1", "?anon_2"),
        ], "?d ?o ?anon_1 ?anon_2 ?inventory ?compared ?unavailable ?examined", stratum=2,
            aggregates=[count_domain("offer", ("_",), "?inventory"),
                        count_domain("comparison", ("?d", "?o", "_", "_", "_"), "?compared"),
                        count_domain("excluded", ("?d", "_"), "?unavailable", 1)],
            assignments=[{"left": "?compared", "op": "add", "right": "?unavailable", "var": "?examined"}],
            conditions=[{"left": "?examined", "op": "eq", "right": "?inventory"}]),
    ], demand="id", offer="id", priced="demand offer total:int rank:int",
        eligible="demand offer total:int rank:int", eligible_offer="demand offer",
        comparison="demand winner contender total:int rank:int", excluded="demand offer", selected="demand offer")

    inventory = [("a",), ("b",), ("c",)]
    a, b = ("d", "a", "80", "1"), ("d", "b", "80", "2")
    aa, ab, bb = ("d", "a", "a", "80", "1"), ("d", "a", "b", "80", "2"), ("d", "b", "b", "80", "2")
    selected, excluded = ("d", "a"), ("d", "c")
    rows = {"demand": [("d",)], "offer": inventory, "priced": [a, b], "eligible": [a, b],
            "eligible_offer": [("d", "a"), ("d", "b")], "comparison": [aa, ab, bb],
            "excluded": [excluded], "selected": [selected]}
    witnesses = [
        witness("selected", "selected", selected, dict(d="d", o="a", anon_1="80", anon_2="1",
                inventory="3", compared="2", unavailable="1", examined="3"), evidence("eligible", a),
                aggregates=[counted("offer", 0, (), inventory), counted("comparison", 1, selected, [aa, ab]),
                            counted("excluded", 2, ("d",), [excluded])]),
        witness("eligible", "eligible", a, dict(d="d", o="a", total="80", rank="1"), evidence("priced", a)),
        witness("eligible", "eligible", b, dict(d="d", o="b", total="80", rank="2"), evidence("priced", b)),
        witness("eligible_offer", "eligible_offer", ("d", "a"), dict(d="d", o="a", total="80", rank="1"),
                evidence("eligible", a)),
        witness("eligible_offer", "eligible_offer", ("d", "b"), dict(d="d", o="b", total="80", rank="2"),
                evidence("eligible", b)),
        witness("comparison_1", "comparison", aa, dict(d="d", o="a", total="80", rank="1"),
                evidence("eligible", a)),
        witness("comparison_3", "comparison", ab, dict(d="d", o="a", other="b", total="80", rank="1", later="2"),
                evidence("eligible", a), evidence("eligible", b)),
        witness("comparison_1", "comparison", bb, dict(d="d", o="b", total="80", rank="2"),
                evidence("eligible", b)),
        witness("excluded", "excluded", excluded, dict(d="d", o="c"), evidence("demand", ("d",)),
                evidence("offer", ("c",)), evidence("eligible_offer", excluded, polarity="negative")),
    ]
    return doc, rows, witnesses


def rejects(report, reason, **labels):
    assert not report["valid"], report
    assert any(f["reason"] == reason and all(f.get(k) == v for k, v in labels.items())
               for f in report["findings"]), report


@pytest.mark.xfail(
    strict=True,
    raises=pytest.RaisesExc(AssertionError, match="A proof left out a tied contender"),
    reason="Read decisions/language-native-rules.md sections 4, 5 and 11. In checker/rezono_checker, "
           "independently check that a complete derived comparison snapshot used by a proof includes the "
           "tied contender required by the frozen rules, even if the reported groups still add up.",
)
def test_native_rule_proof_mutations():
    doc, rows, witnesses = scoped_sweep()
    for report in (epoch(doc, rows, witnesses), proof(doc, rows, witnesses)):
        assert report["valid"] and not report["findings"], report

    missing_certificate = deepcopy(witnesses)
    del missing_certificate[0]["premises"][1]
    rejects(proof(doc, rows, missing_certificate), "premise_mismatch")

    changed_binding = deepcopy(witnesses)
    next(b for b in changed_binding[0]["bindings"] if b["variable"] == "?item")["value"] = "other_sensor"
    rejects(proof(doc, rows, changed_binding), "head_mismatch", relation="absent")

    doc, rows, witnesses = tied_offers()
    for report in (epoch(doc, rows, witnesses), proof(doc, rows, witnesses[:2])):
        assert report["valid"] and not report["findings"], report

    hidden_domain = proof(doc, rows, witnesses[:2], filtered={"comparison"})
    rejects(hidden_domain, "snapshot_missing", relation="comparison")

    swapped_group = deepcopy(witnesses[:2])
    swapped_group[0]["aggregates"][1] = counted("comparison", 1, ("d", "b"), [("d", "b", "b", "80", "2")])
    rejects(proof(doc, rows, swapped_group), "aggregate_mismatch", relation="comparison", key=key("d", "a"))

    # The inventory still includes b and the same-price offer is eligible. Omitting its valid
    # comparison and counting it as excluded preserves the total and each advertised group digest.
    omitted = ("d", "a", "b", "80", "2")
    edited = rows | {"comparison": [row for row in rows["comparison"] if row != omitted],
                     "excluded": [("d", "b"), ("d", "c")]}
    changed = deepcopy(witnesses[:2])
    for binding in changed[0]["bindings"]:
        if binding["variable"] in ("?compared", "?unavailable"):
            binding["value"] = "1" if binding["variable"] == "?compared" else "2"
    changed[0]["aggregates"][1] = counted("comparison", 1, ("d", "a"), [("d", "a", "a", "80", "1")])
    changed[0]["aggregates"][2] = counted("excluded", 2, ("d",), [("d", "b"), ("d", "c")])

    epoch_witnesses = changed + [w for w in witnesses[2:] if w["conclusion"]["key"] != key(*omitted)]
    rejects(epoch(doc, edited, epoch_witnesses), "underived_row", relation="comparison", key=key(*omitted))
    report = proof(doc, edited, changed)
    assert not report["valid"], f"A proof left out a tied contender: {report}"
