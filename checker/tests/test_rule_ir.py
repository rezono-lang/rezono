"""The checker on the compiler's rule IR (contracts/rules.yaml): a sum over a key column, a condition and
an assignment. Hand-written, so it does not depend on the compiler."""

import copy
import hashlib
import json

import pytest

from rezono_checker.canon import encode_key, sha256_json
from rezono_checker.check import check
from rezono_checker.rules import load_rules

IR = {
    "format": "rezono.rules/1", "pack": "example",
    "relations": [
        {"name": "entry", "role": "base", "key": [{"name": "id", "type": "string"}]},
        {"name": "line", "role": "base", "key": [{"name": "entry", "type": "string"}, {"name": "line", "type": "string"},
                                                  {"name": "amount", "type": "integer"}]},
        {"name": "entry_total", "role": "derived", "module": "m", "explain": "materialize",
         "key": [{"name": "entry", "type": "string"}, {"name": "total", "type": "integer"}]},
        {"name": "over", "role": "derived", "module": "m", "explain": "materialize",
         "key": [{"name": "entry", "type": "string"}, {"name": "excess", "type": "integer"}]},
    ],
    "rules": [
        {"id": "entry_total", "module": "m", "stratum": "1", "head": {"relation": "entry_total", "terms": ["?e", "?t"]},
         "body": [{"relation": "entry", "terms": ["?e"], "polarity": "positive", "stratum": "0"}],
         "aggregates": [{"relation": "line", "terms": ["?e", "_", "_"], "function": "sum", "over": "amount", "as": "?t",
                         "stratum": "0"}],
         "witness": {"relation": "entry_total__witness", "variables": ["?e", "?t"]}, "origin": {"file": "r.dl", "line": "1"}},
        {"id": "over", "module": "m", "stratum": "1", "head": {"relation": "over", "terms": ["?e", "?x"]},
         "body": [{"relation": "entry_total", "terms": ["?e", "?t"], "polarity": "positive", "stratum": "1"}],
         "conditions": [{"op": "gt", "left": "?t", "right": "10"}],
         "assignments": [{"var": "?x", "op": "sub", "left": "?t", "right": "10"}],
         "witness": {"relation": "over__witness", "variables": ["?e", "?t", "?x"]}, "origin": {"file": "r.dl", "line": "2"}},
    ],
}
# Two lines with the same amount: both count, because the line is part of the key.
ROWS = {"entry": [["e1"]], "line": [["e1", "a", "7"], ["e1", "b", "7"]], "entry_total": [["e1", "14"]], "over": [["e1", "4"]]}


def world(rows=ROWS):
    snaps = {r: json.dumps([{"key": k} for k in rs]).encode() for r, rs in rows.items()}
    manifest = {"id": "m-1", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                            "sha256": hashlib.sha256(b).hexdigest()} for r, b in snaps.items()]}
    return manifest, snaps.__getitem__


def proof(total="14", excess="4"):
    members = sorted(encode_key(r) for r in ROWS["line"])
    return {"root": {"relation": "over", "key": encode_key(["e1", excess])}, "manifest_id": "m-1", "witnesses": [
        {"conclusion": {"relation": "entry_total", "key": encode_key(["e1", total])}, "rule_id": "entry_total",
         "bindings": [{"variable": "?e", "value": "e1"}, {"variable": "?t", "value": total}],
         "premises": [{"row": {"relation": "entry", "key": encode_key(["e1"])}, "polarity": "positive", "stratum": 0}],
         "aggregates": [{"relation": "line", "group_key": encode_key(["e1"]), "count": 2,
                         "contributors_sha256": sha256_json([[k, "known:7"] for k in members]), "result": "known:14"}]},
        {"conclusion": {"relation": "over", "key": encode_key(["e1", excess])}, "rule_id": "over",
         "bindings": [{"variable": "?e", "value": "e1"}, {"variable": "?t", "value": total}, {"variable": "?x", "value": excess}],
         "premises": [{"row": {"relation": "entry_total", "key": encode_key(["e1", total])}, "polarity": "positive", "stratum": 1}]},
    ]}


def reasons(report):
    return sorted({f["reason"] for f in report["findings"] if f["severity"] == "error"})


def test_a_valid_proof_over_the_rule_ir():
    report = check(proof(), *world()[:1], load_rules(IR), world()[1])
    assert report["valid"] and not report["findings"], report["findings"]


def test_a_wrong_assignment_is_refused():
    rows = copy.deepcopy(ROWS)
    rows["over"] = [["e1", "5"]]
    manifest, read = world(rows)
    assert "assignment_mismatch" in reasons(check(proof(excess="5"), manifest, load_rules(IR), read))


MIN = str(-2**63)
OVERFLOW = {
    "format": "rezono.rules/1", "pack": "example",
    "relations": [
        {"name": "size", "role": "base", "key": [{"name": "id", "type": "string"}, {"name": "n", "type": "integer"}]},
        {"name": "half", "role": "derived", "module": "m", "explain": "materialize",
         "key": [{"name": "id", "type": "string"}, {"name": "n", "type": "integer"}]},
    ],
    "rules": [
        {"id": "half", "module": "m", "stratum": "1", "head": {"relation": "half", "terms": ["?a", "?n"]},
         "body": [{"relation": "size", "terms": ["?a", "?s"], "polarity": "positive", "stratum": "0"}],
         "assignments": [{"var": "?t", "op": "div", "left": "?s", "right": "-1"},
                         {"var": "?n", "op": "div", "left": "?t", "right": "2"}],
         "witness": {"relation": "half__witness", "variables": ["?a", "?n", "?s", "?t"]}, "origin": {"file": "r.dl", "line": "1"}},
    ],
}


@pytest.mark.parametrize("s, t, n, bad", [(MIN, str(2**63), str(2**62), True), ("-8", "8", "4", False)])
def test_an_intermediate_value_outside_bigint_is_refused(s, t, n, bad):
    """Review of #208: -2^63 / -1 is 2^63, outside BIGINT. Feldera and DuckDB stop there, so a proof that
    goes on (n = t / 2 fits again) must not pass. The same bound holds for +, - and *."""
    rows = {"size": [["e1", s]], "half": [["e1", n]]}
    manifest, read = world(rows)
    w = {"conclusion": {"relation": "half", "key": encode_key(["e1", n])}, "rule_id": "half",
         "bindings": [{"variable": "?a", "value": "e1"}, {"variable": "?n", "value": n}, {"variable": "?s", "value": s},
                      {"variable": "?t", "value": t}],
         "premises": [{"row": {"relation": "size", "key": encode_key(["e1", s])}, "polarity": "positive", "stratum": 0}]}
    report = check({"root": w["conclusion"], "manifest_id": "m-1", "witnesses": [w]}, manifest, load_rules(OVERFLOW), read)
    assert reasons(report) == (["arithmetic_overflow"] if bad else [])
    assert report["valid"] is not bad


def test_a_constant_outside_bigint_is_refused():
    """Review of #208: x = t - 2^63 (an operand no engine has: SQL casts it to BIGINT) is refused, even where
    the result would fit. The compiler refuses the constant too (constant_out_of_range)."""
    rules = copy.deepcopy(IR)
    rules["rules"][1]["assignments"] = [{"var": "?x", "op": "sub", "left": "?t", "right": str(2**63)}]
    rows = copy.deepcopy(ROWS)
    rows["over"] = [["e1", str(14 - 2**63)]]
    manifest, read = world(rows)
    report = check(proof(excess=str(14 - 2**63)), manifest, load_rules(rules), read)
    assert reasons(report) == ["arithmetic_overflow"] and not report["valid"]


def test_a_sum_outside_bigint_is_refused_before_it_is_used():
    """Review of #208: the sum of 2^63 - 1 and 2^63 - 2 lies outside BIGINT, where every engine stops; what
    follows from it (here t - 10) must not pass."""
    big = [["e1", "a", str(2**63 - 1)], ["e1", "b", str(2**63 - 2)]]
    total, excess = str(2**64 - 3), str(2**64 - 13)
    rows = {"entry": [["e1"]], "line": big, "entry_total": [["e1", total]], "over": [["e1", excess]]}
    manifest, read = world(rows)
    p = proof(total, excess)
    agg = p["witnesses"][0]["aggregates"][0]
    agg["contributors_sha256"] = sha256_json([[k, f"known:{v}"] for k, v in sorted((encode_key(r), r[2]) for r in big)])
    agg["result"] = f"known:{total}"
    report = check(p, manifest, load_rules(IR), read)
    assert reasons(report) == ["arithmetic_overflow"] and not report["valid"]
    assert {f.get("detail") for f in report["findings"] if f["reason"] == "arithmetic_overflow"} == {"?t", "?x"}


def test_a_false_condition_is_refused():
    rules = copy.deepcopy(IR)
    rules["rules"][1]["conditions"][0]["right"] = "20"     # 14 > 20 does not hold
    manifest, read = world()
    assert reasons(check(proof(), manifest, load_rules(rules), read)) == ["condition_false"]


def test_a_sum_that_counts_equal_amounts_once_is_refused():
    rows = copy.deepcopy(ROWS)
    rows["entry_total"], rows["over"] = [["e1", "7"]], [["e1", "-3"]]
    manifest, read = world(rows)
    p = proof(total="7", excess="-3")
    p["witnesses"][0]["aggregates"][0]["result"] = "known:7"
    assert {"aggregate_result", "condition_false"} <= set(reasons(check(p, manifest, load_rules(IR), read)))


def test_over_a_key_column_needs_the_wildcard():
    rules = copy.deepcopy(IR)
    rules["rules"][0]["aggregates"][0]["terms"] = ["?e", "_", "?t"]
    with pytest.raises(ValueError, match="must range over it"):
        load_rules(rules)


def test_a_missing_binding_of_a_calculated_variable_is_refused():
    """Review of #13: without ?x the assignment and the head could not be checked; that never passes."""
    p = proof()
    p["witnesses"][1]["bindings"] = [b for b in p["witnesses"][1]["bindings"] if b["variable"] != "?x"]
    manifest, read = world()
    report = check(p, manifest, load_rules(IR), read)
    assert not report["valid"] and "unbound_variable" in reasons(report)


def test_two_aggregates_over_one_group_are_told_apart_by_position():
    """Review of #13: a count and a sum over the same relation and group each keep their evidence."""
    rules = copy.deepcopy(IR)
    rule = rules["rules"][0]
    rule["head"]["terms"] = ["?e", "?t"]
    rule["aggregates"].insert(0, {"relation": "line", "terms": ["?e", "_", "_"], "function": "count", "as": "?n",
                                  "stratum": "0"})
    rule["witness"]["variables"] = ["?e", "?n", "?t"]
    p = proof()
    w = p["witnesses"][0]
    w["bindings"].insert(1, {"variable": "?n", "value": "2"})
    members = sorted(encode_key(r) for r in ROWS["line"])
    total = dict(w["aggregates"][0], position=1)
    count = {"relation": "line", "position": 0, "group_key": encode_key(["e1"]), "count": 2,
             "contributors_sha256": sha256_json([[k] for k in members]), "result": "known:2"}
    w["aggregates"] = [total, count]          # order in the proof does not matter, the position does
    manifest, read = world()
    report = check(p, manifest, load_rules(rules), read)
    assert report["valid"] and not report["findings"], report["findings"]
    count["position"] = 1                      # two at one position: refused
    assert "aggregate_mismatch" in reasons(check(p, manifest, load_rules(rules), read))


def test_a_proof_may_mix_aggregates_with_and_without_position():
    """Second review of #13: `position` is optional; one aggregate with it and one without both count."""
    rules = copy.deepcopy(IR)
    rule = rules["rules"][0]
    rule["aggregates"].insert(0, {"relation": "entry", "terms": ["?e"], "function": "count", "as": "?n", "stratum": "0"})
    rule["witness"]["variables"] = ["?e", "?n", "?t"]
    p = proof()
    w = p["witnesses"][0]
    w["bindings"].insert(1, {"variable": "?n", "value": "1"})
    count = {"relation": "entry", "position": 0, "group_key": encode_key(["e1"]), "count": 1,
             "contributors_sha256": sha256_json([[encode_key(["e1"])]]), "result": "known:1"}
    w["aggregates"] = [w["aggregates"][0], count]          # the sum without a position, the count with one
    manifest, read = world()
    report = check(p, manifest, load_rules(rules), read)
    assert report["valid"] and not report["findings"], report["findings"]
    count["position"] = 5                                  # a position the rule does not have
    assert "aggregate_mismatch" in reasons(check(p, manifest, load_rules(rules), read))


def test_epoch_every_witness_and_complete():
    """check_epoch: all witnesses of an epoch at once, and every derived row has exactly one."""
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations

    manifest, read = world()
    witnesses = proof()["witnesses"]
    rules = load_rules(IR)
    derived = derived_relations(IR, rules)
    assert derived == {"entry_total", "over"}
    report = check_epoch(witnesses, manifest, rules, read, derived=derived)
    assert report["valid"] and report["findings"] == [] and "root" not in report
    def reasons(ws, rows=ROWS):
        m, r = world(rows)
        return {f["reason"] for f in check_epoch(ws, m, rules, r, derived=derived)["findings"]}

    assert reasons(witnesses[:1]) == {"unproven_row"}  # over(e1, 4) has no witness
    assert "unproven_premise" in reasons(witnesses[1:])  # nor entry_total(e1, 14), which over uses
    assert "duplicate_witness" in reasons([*witnesses, witnesses[0]])
    extra = {**ROWS, "over": [["e1", "4"], ["e1", "5"]]}
    assert reasons(witnesses, extra) == {"unproven_row"}  # a published derived row nobody proved
    wrong = copy.deepcopy(witnesses)
    wrong[0]["aggregates"][0]["contributors_sha256"] = "0" * 64
    assert reasons(wrong) == {"aggregate_contributors"}

    assert reasons([{}, *witnesses]) == {"malformed_witness"}
    assert reasons([*witnesses, {"conclusion": {"relation": "over"}, "rule_id": "over"}]) == {"malformed_witness"}


def test_the_checker_binds_numeric_selections_and_refuses_an_unsafe_rule_phase():
    from rezono_checker.rules import check_calc_bindings

    doc = copy.deepcopy(IR)
    name = "calc__amount"
    declaration = {"name": name, "role": "calc", "world": "open", "key": [
        {"name": key, "type": typ} for key, typ in
        (("subject", "string"), ("value", "integer"), ("state", "string"), ("reason", "string"))
    ]}
    doc["relations"].append(declaration)
    premise = {"relation": name, "terms": ["?e", "?amount", "known", ""], "polarity": "positive", "stratum": "0"}
    doc["rules"][1]["body"].append(premise)
    calculation = {"rules": [{"view": name, "type": "number"}], "facts": [{"table": "entry_total"}]}

    def checked():
        check_calc_bindings(doc, load_rules(doc), calculation)

    checked()
    declaration["role"] = "base"
    with pytest.raises(ValueError, match="need a calc declaration"):
        checked()
    declaration["role"] = "calc"
    calculation["rules"][0]["type"] = "boolean"
    with pytest.raises(ValueError, match="numeric calculation selection"):
        checked()
    calculation["rules"][0]["type"] = "number"
    premise["terms"][2] = "?state"
    with pytest.raises(ValueError, match="selections known"):
        checked()
    premise["terms"][2] = "known"
    calculation["facts"][0]["table"] = "over"
    with pytest.raises(ValueError, match="reads its downstream relations"):
        checked()
    calculation["facts"][0]["table"] = "entry_total"
    doc["rules"].append({"id": "grant", "stratum": "1", "head": {"relation": "may_read", "terms": ["?e"]},
                         "body": [{"relation": "over", "terms": ["?e", "?x"], "polarity": "positive", "stratum": "1"}]})
    with pytest.raises(ValueError, match="may_read cannot depend"):
        checked()
    doc["rules"][-1]["head"]["relation"] = "absence"
    doc["rules"][-1]["stratum"] = "2"
    doc["rules"][-1]["body"][0]["polarity"] = "negative"
    doc["rules"][-1]["body"].append({"relation": "line", "terms": ["?e", "?l", "?x"], "polarity": "positive", "stratum": "0"})
    with pytest.raises(ValueError, match="over is open"):  # W6 first: a calculation selection is open
        checked()
    doc["relations"].append({"name": "absence", "role": "derived", "absence": True,
                             "key": [{"name": "entry", "type": "string"}]})
    with pytest.raises(ValueError, match="premises must be positive"):
        checked()


def test_rule_and_calculation_witnesses_form_one_acyclic_graph():
    from rezono_checker.check import _check_graph

    doc = proof()
    doc["root"] = None
    early, late = doc["witnesses"]
    calc_row = {"relation": "calc__amount", "key": encode_key(["e1", "14", "known", ""])}
    late["premises"].append({"row": calc_row, "polarity": "positive", "stratum": 0})
    calculated = {"conclusion": calc_row, "state": "known", "value": "14", "premises": [early["conclusion"]]}
    rules = load_rules(IR)

    def reasons(*witnesses):
        findings = []
        _check_graph(doc, rules, findings, witnesses, {calc_row["relation"]})
        return {finding["reason"] for finding in findings}

    assert not reasons(calculated)
    assert reasons() == {"unproven_premise"}
    assert reasons(calculated, calculated) == {"duplicate_witness"}
    assert reasons({**calculated, "premises": [late["conclusion"]]}) == {"cycle"}
    assert reasons({**calculated, "value": "3/2"}) == {"bad_calc_premise"}


def test_epoch_checks_calculation_before_accepting_a_consuming_rule(tmp_path, capsys):
    from rezono_checker.__main__ import main
    from rezono_checker.check import check_epoch

    amount = "calc__amount"
    date = "2026-11-01"
    calc_key = ["e1", "14", "known", ""]
    manifest, read = world({**ROWS, amount: [calc_key], "calc__as_of": [["as_of", date, date]]})
    doc = copy.deepcopy(IR)
    doc["relations"].append({"name": amount, "role": "calc", "world": "open", "key": [
        {"name": name, "type": typ} for name, typ in
        (("subject", "string"), ("value", "integer"), ("state", "string"), ("reason", "string"))
    ]})
    doc["rules"][1]["body"] = [{
        "relation": amount, "terms": ["?e", "?t", "known", ""], "polarity": "positive", "stratum": "0"
    }]
    early, late = proof()["witnesses"]
    selection = {"relation": amount, "key": encode_key(calc_key)}
    late["premises"] = [{"row": selection, "polarity": "positive", "stratum": 0}]
    calculation = {
        "subject": "Entry", "subject_table": "entry", "as_of": "calc__as_of",
        "facts": [{"id": "total", "type": "number", "reads": "column", "table": "entry_total", "index": 1}],
        "rules": [{"rule": "amount", "view": amount, "type": "number", "versions": ["amount@v1"]}],
        "versions": [{"id": "amount@v1", "version": "v1", "view": "calc__amount__v1", "rule": "amount",
                      "valid_from": date, "valid_until": "2026-12-01", "known_from": date,
                      "definitions": [{"name": "total", "when": {"boolean": True}, "value": {"fact": "total"}}]}],
    }
    calculated = {"conclusion": selection, "rule": "amount", "version": "v1", "definition": "total",
                  "valid_at": date, "known_at": date, "state": "known", "value": "14", "reason": "",
                  "reads": ["calc__as_of", "entry_total"], "premises": [early["conclusion"]],
                  "steps": [{"path": "total/value", "op": "fact", "ref": "total", "relation": "entry_total",
                             "state": "known", "value": "14"}]}

    def checked(*calc_witnesses):
        return check_epoch([early, late], manifest, load_rules(doc), read, derived={"entry_total", "over"},
                           calc_witnesses=calc_witnesses, calc_ir=calculation)

    assert checked(calculated)["valid"]
    assert "unproven_premise" in reasons(checked())
    bad = copy.deepcopy(calculated)
    bad["steps"][0]["value"] = "13"
    assert "calc_leaf" in reasons(checked(bad))

    # A correctly hashed snapshot is not evidence that its claimed calculation was performed.
    forged_key = ["e1", "99", "known", ""]
    forged_manifest, forged_read = world({**ROWS, amount: [forged_key], "over": [["e1", "89"]]})
    forged = proof(total="99", excess="89")
    forged_late = forged["witnesses"][1]
    forged_late["premises"] = [{"row": {"relation": amount, "key": encode_key(forged_key)},
                               "polarity": "positive", "stratum": 0}]
    forged["witnesses"] = [early, forged_late]
    definitions = load_rules(doc)
    assert "unproven_premise" in reasons(check(forged, forged_manifest, definitions, forged_read))
    assert "unproven_premise" in reasons(check_epoch(
        forged["witnesses"], forged_manifest, definitions, forged_read, derived={"entry_total", "over"}
    ))
    for snapshot in forged_manifest["snapshots"]:
        uri = snapshot["uri"]
        (tmp_path / uri).write_bytes(forged_read(uri))
    for name, value in (("proof", forged), ("manifest", forged_manifest), ("rules", doc)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    assert main(["--proof", str(tmp_path / "proof.json"), "--manifest", str(tmp_path / "manifest.json"),
                 "--rules", str(tmp_path / "rules.json")]) == 1
    assert "unproven_premise" in reasons(json.loads(capsys.readouterr().out))


def test_epoch_for_a_role_negation_and_aggregates_only_over_full_relations():
    """O8: for one role, a witness may aggregate or negate only over a relation it reads in full."""
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations

    manifest, read = world()
    witnesses = proof()["witnesses"]
    rules = load_rules(IR)
    derived = derived_relations(IR, rules)
    full = check_epoch(witnesses, manifest, rules, read, derived=derived, full={"entry", "line", "entry_total", "over"})
    assert full["valid"], full["findings"]
    partial = check_epoch(witnesses, manifest, rules, read, derived=derived, full={"entry", "entry_total", "over"})
    assert {(f["reason"], f["relation"]) for f in partial["findings"]} == {("outside_full_scope", "line")}
    assert not partial["valid"]


def test_the_catalogue_of_derived_relations_is_kept():
    """A declared derived relation without a rule is refused; so is a rule head that is not declared."""
    from rezono_checker.rules import derived_relations

    no_rule = {**IR, "rules": [r for r in IR["rules"] if r["id"] != "over"]}
    with pytest.raises(ValueError, match="without a rule"):
        derived_relations(no_rule, load_rules(no_rule))
    undeclared = {**IR, "relations": [r for r in IR["relations"] if r["name"] != "over"]}
    with pytest.raises(ValueError, match="not declared"):
        derived_relations(undeclared, load_rules(undeclared))


def extension_ir():
    doc = copy.deepcopy(IR)
    doc["relations"].append({"name": "granted", "role": "derived", "module": "access", "extend": True,
                             "key": [{"name": "role", "type": "string"}, {"name": "kind", "type": "string"},
                                     {"name": "element", "type": "string"}]})
    return doc


def test_a_declaration_only_extension_is_derived_and_its_snapshot_must_be_empty():
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations

    doc = extension_ir()
    rules = load_rules(doc)
    derived = derived_relations(doc, rules)
    assert "granted" in derived
    manifest, read = world({**ROWS, "granted": []})
    assert check_epoch(proof()["witnesses"], manifest, rules, read, derived=derived)["valid"]
    manifest, read = world({**ROWS, "granted": [["reader", "entry", "e1"]]})
    report = check_epoch(proof()["witnesses"], manifest, rules, read, derived=derived)
    assert not report["valid"] and reasons(report) == ["unproven_row"]
    manifest, read = world()
    report = check_epoch(proof()["witnesses"], manifest, rules, read, derived=derived)
    assert not report["valid"] and reasons(report) == ["snapshot_missing"]


@pytest.mark.parametrize("value", [None, False, "true", 1])
def test_the_empty_extension_exception_requires_an_explicit_typed_true(value):
    from rezono_checker.rules import derived_relations
    doc = extension_ir()
    if value is None:
        del doc["relations"][-1]["extend"]
    else:
        doc["relations"][-1]["extend"] = value
    with pytest.raises(ValueError, match="without a rule|extend is a boolean"):
        derived_relations(doc, load_rules(doc))


def test_a_base_relation_cannot_claim_the_extension_exception():
    from rezono_checker.rules import derived_relations
    doc = extension_ir()
    doc["relations"][-1]["role"] = "base"
    with pytest.raises(ValueError, match="extend is a boolean"):
        derived_relations(doc, load_rules(doc))


@pytest.mark.parametrize("rule_id", ["fabricated", "entry_total"])
def test_forged_extension_witnesses_cannot_prove_a_nonempty_snapshot(rule_id):
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import derived_relations
    doc = extension_ir()
    rules = load_rules(doc)
    forged = copy.deepcopy(proof()["witnesses"][0])
    forged["rule_id"] = rule_id
    forged["conclusion"] = {"relation": "granted", "key": encode_key(["reader", "entry", "e1"])}
    manifest, read = world({**ROWS, "granted": [["reader", "entry", "e1"]]})
    report = check_epoch([*proof()["witnesses"], forged], manifest, rules, read,
                         derived=derived_relations(doc, rules))
    assert not report["valid"]
    assert ("unknown_rule" if rule_id == "fabricated" else "head_mismatch") in reasons(report)


def test_the_aggregate_index_gives_the_same_result():
    """recompute with a shared index per source relation equals the plain scan, for every group."""
    from rezono_checker.check import recompute
    from rezono_checker.snapshots import read_rows

    rule = load_rules(IR)["entry_total"]
    spec = rule.aggregates[0]
    rows = read_rows(json.dumps([{"key": [e, str(i), str(i % 7)]} for e in ("e1", "e2", "e3") for i in range(50)]).encode(), "json")
    groups = {}
    for e in ("e1", "e2", "e3", "e4"):
        assert recompute(spec, [(0, e)], rows, groups) == recompute(spec, [(0, e)], rows)
    assert len(groups) == 1



SEAL = {"kind": "run", "period": "run__month", "row_sha256": "run__row_sha256", "tables": ["run__hours", "run__month"],
        "closed_until": "period_close__closed_until", "covers": "period_close__covers", "element": "closed_run__element",
        "sha256": "closed_run__sha256", "refused": "run__refused", "accepted": "run__accepted"}


def sealed():
    """October closed: r1 covered as it is, r2 never covered (late), r3 for November."""
    from rezono_canon import canonical_sha256

    hours = {"r1": "2", "r2": "3", "r3": "2"}
    month = {"r1": "2026-10-01", "r2": "2026-10-01", "r3": "2026-11-01"}
    h = {r: canonical_sha256({"run__hours": [hours[r]], "run__month": [month[r]]}) for r in hours}
    return h, {"run": [["r1"], ["r2"], ["r3"]], "run__hours": [[r, v] for r, v in hours.items()],
               "run__month": [[r, v] for r, v in month.items()], "run__row_sha256": [[r, v] for r, v in h.items()],
               "period_close__closed_until": [["c1", "2026-11-01"]], "period_close__covers": [["c1", "c1/1"]],
               "closed_run__element": [["c1/1", "r1"]], "closed_run__sha256": [["c1/1", h["r1"]]],
               "run__refused": [["r2", "c1"]], "run__accepted": [["r1"], ["r3"]]}


def test_epoch_recomputes_a_seal():
    """check_epoch with seals (decision E3): row hashes, refused and accepted input are what the snapshots give."""
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import load_seals

    seals = load_seals({"format": "rezono.rules/1", "pack": "example", "relations": [], "rules": [], "seals": [SEAL]})
    h, rows = sealed()

    def reasons(changed):
        m, r = world({**rows, **changed})
        return sorted((f["reason"], f.get("relation")) for f in check_epoch([], m, {}, r, derived=set(), seals=seals)["findings"])

    assert reasons({}) == []
    assert reasons({"run__refused": [], "run__accepted": [["r1"], ["r2"], ["r3"]]}) == [
        ("seal_mismatch", "run__accepted"), ("seal_mismatch", "run__refused")]  # a late run counted
    assert reasons({"run__accepted": [["r1"]]}) == [("seal_mismatch", "run__accepted")]  # a missing row
    edited = {"run__hours": [["r1", "9"], ["r2", "3"], ["r3", "2"]]}  # r1 edited after the close, hash not updated
    assert reasons(edited) == [("seal_mismatch", "run__accepted"), ("seal_mismatch", "run__refused"),
                               ("seal_mismatch", "run__row_sha256"), ("seal_mismatch", "run__row_sha256")]
    assert reasons({"period_close__closed_until": [["c1", "1 November"]]}) == [
        ("seal_bad_date", "period_close__closed_until"), ("seal_mismatch", "run__accepted"),
        ("seal_mismatch", "run__refused")]
    with pytest.raises(ValueError):
        load_seals({"seals": [{**SEAL, "kind": 1}]})


def test_a_forged_seal_is_found():
    """Review P1: each forgery claims the rows the old rule would have given; the checker refuses them."""
    from rezono_canon import canonical_sha256
    from rezono_checker.check import check_epoch
    from rezono_checker.rules import load_seals

    h, rows = sealed()

    def reasons(changed, seal=SEAL):
        seals = load_seals({"format": "rezono.rules/1", "pack": "example", "relations": [], "rules": [], "seals": [seal]})
        m, r = world({**rows, **changed})
        return sorted((f["reason"], f.get("relation")) for f in check_epoch([], m, {}, r, derived=set(), seals=seals)["findings"])

    both = [("seal_mismatch", "run__accepted"), ("seal_mismatch", "run__refused")]
    # r1, covered in October, moved to November and edited; its row hash is updated, its cover is not
    moved = canonical_sha256({"run__hours": ["9"], "run__month": ["2026-11-15"]})
    assert reasons({"run__hours": [["r1", "9"], ["r2", "3"], ["r3", "2"]],
                    "run__month": [["r1", "2026-11-15"], ["r2", "2026-10-01"], ["r3", "2026-11-01"]],
                    "run__row_sha256": [["r1", moved], ["r2", h["r2"]], ["r3", h["r3"]]]}) == both
    # a later close covers the late r2 with its hash: c1 still refuses it
    assert reasons({"period_close__closed_until": [["c1", "2026-11-01"], ["c2", "2026-12-01"]],
                    "period_close__covers": [["c1", "c1/1"], ["c2", "c2/1"], ["c2", "c2/2"], ["c2", "c2/3"]],
                    "closed_run__element": [["c1/1", "r1"], ["c2/1", "r1"], ["c2/2", "r2"], ["c2/3", "r3"]],
                    "closed_run__sha256": [["c1/1", h["r1"]], ["c2/1", h["r1"]], ["c2/2", h["r2"]], ["c2/3", h["r3"]]],
                    "run__refused": [], "run__accepted": [["r1"], ["r2"], ["r3"]]}) == both
    # r1 joins the subkind run_big after the close; the snapshot keeps its old hash
    big = {**SEAL, "tables": ["run__hours", "run__month", "run_big"]}
    assert reasons({"run_big": [["r1"]]}, big) == [("seal_mismatch", "run__accepted"), ("seal_mismatch", "run__refused"),
                                                     ("seal_mismatch", "run__row_sha256"), ("seal_mismatch", "run__row_sha256")]
