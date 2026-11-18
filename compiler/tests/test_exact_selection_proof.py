"""An exact selection can ground a value-preserving rule only with its checked calculation."""

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
import yaml

from calcsupport import checked, connect, snapshots
from rezono_checker import closure
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import check_calc_bindings, load_rules
from rezono_compiler import calc, calc_sql, facts, pack


VALUE = "2782/41"  # 26 units at 107 per 41 units. 2782 and 41 are coprime.
SELECTION = "calc__total"


@pytest.fixture
def calculation(tmp_path):
    folder = shutil.copytree(Path(__file__).parent / "fixtures/calc", tmp_path / "calc")
    recipe = folder / "calc/example.yaml"
    doc = yaml.safe_load(recipe.read_bytes())
    doc["rules"][0]["definitions"] = [{"name": "share", "when": {"boolean": True}, "value": {
        "op": "ratio", "args": [{"fact": "item.amount"}, {"parameter": "price"}, {"fact": "item.extra"}]}}]
    recipe.write_text(yaml.safe_dump(doc), encoding="utf-8")
    model = pack.read(folder)
    program = calc.build(model, model.calc)

    def run(*, denominator=True):
        item = {"id": "a", "amount": 26, "flag": True}
        if denominator:
            item["extra"] = 41
        data = facts.rows_of(model, {"item": [item], "setting": [{"id": "price", "value": 107}]})
        data[calc_sql.AS_OF] = [(row["id"], row["valid_at"], row["known_at"]) for row in
                                calc_sql.rows(program)[calc_sql.AS_OF]]
        with closing(connect(model, program, data)) as db:
            assert checked(db, program) == []
            physical = db.execute('SELECT state, n, d FROM "calc__total"').fetchall()
            rows = snapshots(db, program)
            witnesses = calc_sql.witnesses(db, program)
        names = {"item", "item__amount", "item__extra", "setting", "setting__value", "calc__as_of",
                 SELECTION, "calc__total__v1"}
        return physical, {name: rows[name] for name in names}, witnesses

    return calc.to_doc(program), run


def test_selected_share_has_two_independently_recorded_operands_and_a_price(calculation):
    _, run = calculation
    physical, rows, witnesses = run()
    assert physical == [("known", 2782, 41)]
    assert rows[SELECTION] == [("a", VALUE, "known", "")]
    witness, = [w for w in witnesses if w["conclusion"]["relation"] == SELECTION]
    assert witness["value"] == VALUE
    assert [(s["relation"], s["ref"], s["value"]) for s in witness["steps"] if "relation" in s] == [
        ("item__amount", "item.amount", "26"), ("setting__value", "price", "107"),
        ("item__extra", "item.extra", "41")]
    missing, rows, _ = run(denominator=False)
    assert missing[0][0] == "not_applicable"
    assert rows[SELECTION][0][:3] == ("a", "", "not_applicable")


def consumer(value_type):
    columns = [{"name": "subject", "type": "string"}, {"name": "value", "type": value_type}]
    terms = ["?subject", "?value"]
    return {"format": "rezono.rules/1", "pack": "calc", "relations": [
        {"name": SELECTION, "role": "calc", "world": "open", "key": columns + [
            {"name": "state", "type": "string"}, {"name": "reason", "type": "string"}]},
        {"name": "received", "role": "derived", "world": "open", "key": columns}],
        "rules": [{"id": "received", "module": "numbers", "stratum": "1",
                   "head": {"relation": "received", "terms": terms},
                   "body": [{"relation": SELECTION, "terms": terms + ["known", ""],
                             "polarity": "positive", "stratum": "0"}],
                   "witness": {"relation": "received__witness", "variables": terms},
                   "origin": {"file": "numbers.dl", "line": "2"}}]}


def verify(doc, calc_ir, rows, witnesses, *, value=VALUE):
    definitions = load_rules(doc)
    check_calc_bindings(doc, definitions, calc_ir)
    key = ["a", value]
    premises = [{"row": {"relation": SELECTION, "key": encode_key(key + ["known", ""])},
                 "polarity": "positive", "stratum": 0}]
    rule_witness = {"conclusion": {"relation": "received", "key": encode_key(key)}, "rule_id": "received",
                    "bindings": [{"variable": "?subject", "value": "a"}, {"variable": "?value", "value": value}],
                    "premises": premises}
    payloads = {name: json.dumps([{"key": row} for row in values]).encode()
                for name, values in (rows | {"received": [key]}).items()}
    manifest = {"id": "m", "snapshots": [{"relation": name, "role": "all", "complete": True, "uri": name,
                                          "format": "json", "sha256": sha256(data).hexdigest()}
                                         for name, data in sorted(payloads.items())]}
    return check_epoch([rule_witness], manifest, definitions, payloads.__getitem__, derived={"received"},
                       calc_witnesses=witnesses, calc_ir=calc_ir)


@pytest.mark.xfail(strict=True, raises=pytest.RaisesExc(ValueError, match="typed input for a numeric calculation"),
                   reason="Waits for test_native_boolean_rule_inputs and test_independent_date_equality on the shared rule contract. "
                          "Read decisions/exact-calculation-premises.md. In contracts/rules.yaml and "
                          "checker/rezono_checker admit a copy of a proved rational selection in a typed rule. "
                          "Preserve the integer projection and verify the calculation's independent grounds.")
def test_checker_accepts_only_a_proved_exact_selection(calculation):
    calc_ir, run = calculation
    _, rows, witnesses = run()
    exact = consumer("rational")
    report = verify(exact, calc_ir, rows, witnesses)
    assert report["valid"], report["findings"]
    assert not verify(consumer("integer"), calc_ir, rows, witnesses)["valid"]
    contract = Path(__file__).resolve().parents[2] / "contracts/rules.yaml"
    assert "rational" in yaml.safe_load(contract.read_bytes())["enums"]["ColumnType"]["permissible_values"]
    for typ in ("integer", "string"):
        mixed = consumer("rational")
        mixed["relations"][1]["key"] = [{"name": "subject", "type": "string"}, {"name": "value", "type": typ}]
        with pytest.raises(ValueError):
            check_calc_bindings(mixed, load_rules(mixed), calc_ir)
    arithmetic = consumer("rational")
    arithmetic["rules"][0]["conditions"] = [{"left": "?value", "op": "gt", "right": "0"}]
    with pytest.raises(ValueError):
        check_calc_bindings(arithmetic, load_rules(arithmetic), calc_ir)
    findings = closure.check(load_rules(exact), lambda name: {
        encode_key(row): (row, {}) for row in rows.get(name, [])}, read={"received"})
    assert [(f["reason"], f["relation"], f["key"]) for f in findings] == [
        ("underived_row", "received", encode_key(["a", VALUE]))]
    for value in ("67", "68", "5564/82"):
        # Rehash a consistent claim at every layer; the actual calculation inputs still disagree.
        key = ("a", value, "known", "")
        forged = [w | {"conclusion": {"relation": SELECTION, "key": encode_key(key)}, "value": value}
                  if w["conclusion"]["relation"] == SELECTION else w for w in witnesses]
        report = verify(exact, calc_ir, rows | {SELECTION: [key]}, forged, value=value)
        assert any(f["reason"] == "calc_result" for f in report["findings"]), value
    without_selection = [w for w in witnesses if w["conclusion"]["relation"] != SELECTION]
    findings = verify(exact, calc_ir, rows, without_selection)["findings"]
    assert any(f["reason"] == "unproven_premise" and f.get("relation") == SELECTION for f in findings)
    without_date = verify(exact, calc_ir, rows | {"calc__as_of": []}, witnesses)
    assert any(f["reason"] == "calc_version" for f in without_date["findings"])
    for relation in ("item__amount", "setting__value", "item__extra"):
        report = verify(exact, calc_ir, rows | {relation: []}, witnesses)
        assert any(f["reason"] == "calc_leaf" for f in report["findings"]), relation
    _, missing_rows, missing_witnesses = run(denominator=False)
    assert not verify(exact, calc_ir, missing_rows, missing_witnesses)["valid"]
