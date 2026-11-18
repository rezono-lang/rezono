"""Check complete evidence from the same neutral cases independently."""

from copy import deepcopy
import json
from pathlib import Path
from runpy import run_path

import pytest

from rezono_checker.calc import recorded, text
from rezono_checker.check import check, check_epoch
from rezono_checker.rules import derived_relations, load_rules
from rezono_checker.snapshots import read_rows


CORPUS = Path(__file__).resolve().parents[2] / "tests/conformance"
replay = run_path(str(CORPUS / "replay.py"))


class IncompleteAggregateAccepted(AssertionError):
    """The selected aggregate passed with a missing contributor in its scope."""


def verify(case, rule_document, witnesses, snapshots):
    rules = load_rules(rule_document)
    return check_epoch(
        witnesses, replay["manifest"](case, snapshots), rules, snapshots.__getitem__,
        derived=derived_relations(rule_document, rules),
    )


def selected(case):
    return [case["input"]["select"]["id"], case["expect"]["value"]]


@pytest.mark.parametrize("case", replay["cases"]("checker", "snapshot"))
def test_checker_replays_neutral_snapshot(case):
    authored = case["input"]["rows"]
    selection = case["input"]["snapshot"]
    rejected = selection["rejected"]

    rows = dict(read_rows(json.dumps(authored).encode(), "json").values())
    assert rows == {tuple(row["key"]): row["values"] for row in authored}
    cell = rows[tuple(selection["key"])][selection["slot"]]
    with pytest.raises(ValueError) as error:
        read_rows(json.dumps([rejected]).encode(), "json")
    actual = {
        "value": cell.get("value", cell.get("minor_units")), "state": cell["state"],
        "reason": cell.get("reason"), "witness": None, "refusal": str(error.value).partition(": ")[0],
    }
    assert actual == case["expect"]

    if "minor_units" in cell:
        admitted = recorded(cell["state"], cell["minor_units"], "")
        assert admitted is not None and text(admitted.value) == case["expect"]["value"]
        malformed = rejected["values"][selection["slot"]]
        assert recorded(malformed["state"], malformed["minor_units"], "") is None


@pytest.mark.parametrize("case", replay["cases"]("checker"))
def test_checker_replays_neutral_case(case, tmp_path):
    result = replay["play"](case, tmp_path)
    report = verify(case, result.rules, result.witnesses, result.snapshots)
    assert report["valid"] and not report["findings"], report
    assert replay["read_sum"](case, result.rows, result.witnesses) == case["expect"]

    forged = deepcopy(result.witnesses)
    relation = case["input"]["rules"]["output"]
    (witness,) = [w for w in forged if w["conclusion"]["relation"] == relation
                  and json.loads(w["conclusion"]["key"]) == selected(case)]
    witness["aggregates"][0]["contributors_sha256"] = "0" * 64
    report = verify(case, result.rules, forged, result.snapshots)
    assert not report["valid"] and "aggregate_contributors" in {f["reason"] for f in report["findings"]}


def test_checker_refuses_an_incomplete_conformance_aggregate_scope(tmp_path):
    case = replay["case_file"]("value-agg-sum-empty")
    result = replay["play"](case, tmp_path / "original")
    assert replay["read_sum"](case, result.rows, result.witnesses) == case["expect"]
    relation = case["input"]["rules"]["output"]
    (witness,) = [w for w in result.witnesses if w["conclusion"]["relation"] == relation
                  and json.loads(w["conclusion"]["key"]) == selected(case)]
    claim = {"manifest_id": case["id"], "root": witness["conclusion"], "witnesses": [witness]}
    rules = load_rules(result.rules)
    assert check(claim, replay["manifest"](case, result.snapshots), rules, result.snapshots.__getitem__)["valid"]

    # Add one admitted contributor to the selected group. Keep every other group's base rows.
    (example,) = [row for row in case["input"]["rows"] if row["$kind"] == "Item"]
    changed = deepcopy(case)
    changed["input"]["rows"].append({
        **example, "$id": "item-added", "group": {"$ref": selected(case)[0]},
    })
    actual = replay["play"](changed, tmp_path / "with-member")
    assert replay["read_sum"](changed, actual.rows, actual.witnesses)["value"] == example["quantity"]
    contributors = witness["aggregates"][0]["relation"]
    assert actual.rows[contributors] - result.rows[contributors] == {
        (selected(case)[0], "item-added", example["quantity"]),
    }

    # Update the manifest to the admitted inputs. The claimed complete contributor group still omits the new item.
    base = {ref["name"] for ref in result.rules["relations"] if ref["role"] == "base"}
    snapshots = result.snapshots | {name: raw for name, raw in actual.snapshots.items() if name in base}
    report = check(claim, replay["manifest"](case, snapshots), rules, snapshots.__getitem__)
    if report["valid"]:
        raise IncompleteAggregateAccepted(f"{relation}{selected(case)} ignores an admitted contributor")
    assert any(finding["severity"] == "error" and finding.get("relation") in {relation, contributors}
               for finding in report["findings"])
