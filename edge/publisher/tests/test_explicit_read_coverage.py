"""A witnessed whole population and a collection of element rights can cover the same rows."""

import json
import shutil
from pathlib import Path

import pytest
from rezono_checker import access as checker_access
from rezono_publisher import access, batch, publish


RULES = """.decl may_read(role: symbol, kind: symbol, element: symbol)
.decl may_read_full(role: symbol, kind: symbol)
may_read_full("whole", "item") :- permit("scope").
may_read("whole", "item", x) :- permit("scope"), item(x).
may_read("enumerator", "item", x) :- item(x).
may_read("partial", "item", x) :- item__label(x, "visible").
may_read("whole", "permit", x) :- permit(x).
"""

SCHEMA = """id: https://rezono.example/coverage
name: coverage
in_language: en
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
      label: {required: true}
  Permit:
    attributes:
      id: {identifier: true}
"""

FACTS = """item:
  - {id: first, label: visible}
  - {id: second, label: hidden}
permit:
  - {id: scope}
"""


@pytest.fixture(scope="module")
def epoch(tmp_path_factory):
    root = tmp_path_factory.mktemp("coverage")
    (root / "pack.yaml").write_text('name: coverage\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    minimal = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"
    shutil.copytree(minimal / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}, {kind: permit, shape: rect}]\n", encoding="utf-8")
    (root / "labels").mkdir()
    (root / "labels/nl.yaml").write_text("item: Item\nitem.label: Label\npermit: Permit\n", encoding="utf-8")
    for folder, filename, content in (("schema", "coverage.yaml", SCHEMA), ("rules", "rights.dl", RULES),
                                      ("facts", "population.yaml", FACTS)):
        (root / folder).mkdir()
        (root / folder / filename).write_text(content, encoding="utf-8")
    return batch.epoch(root, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])


def filtered(epoch, role):
    return access.for_role(epoch.rows, epoch.kinds, epoch.parents, epoch.columns, json.loads(epoch.rules),
                           epoch.witnesses, role)


def checked(epoch, role, readable, witnesses, full, evidence, instances):
    return checker_access.check_role(
        role, {r: publish.snapshot(rows) for r, rows in epoch.rows.items()},
        {r: publish.snapshot(rows) for r, rows in readable.items()}, full, json.loads(epoch.bundle),
        json.loads(epoch.rules), instances=instances, witnesses=witnesses,
        claimed_evidence=evidence)


def test_element_grants_and_coverage_have_separate_witnesses(epoch):
    assert set(epoch.rows["may_read_full"]) == {("whole", "item")}
    assert {r for r, k, i in epoch.rows["may_read"] if k == "item" and i == "first"} == {"whole", "enumerator", "partial"}
    assert {r for r, k, i in epoch.rows["may_read"] if k == "item" and i == "second"} == {"whole", "enumerator"}
    [proof] = [w for w in epoch.witnesses if w["conclusion"]["relation"] == "may_read_full"]
    assert json.loads(proof["conclusion"]["key"]) == ["whole", "item"]
    assert [(p["row"]["relation"], json.loads(p["row"]["key"])) for p in proof["premises"]] == [("permit", ["scope"])]


def test_publisher_uses_the_witnessed_population_for_explicit_programs(epoch):
    for role, expected in (("whole", {"first", "second"}), ("enumerator", {"first", "second"}),
                           ("partial", {"first"}), ("absent", set())):
        readable, _, full = filtered(epoch, role)
        assert {row[0] for row in readable["item"]} == expected
        assert ("item" in full) == (role == "whole"), role
        assert ("item__label" in full) == (role == "whole"), role
        if role == "whole":
            [proof] = [w for w in epoch.witnesses if w["conclusion"]["relation"] == "may_read_full"]
            assert {"kind": "item", "rule": proof["rule_id"], "ground": ["may_read_full", role, "item"]} in full.evidence
    incomplete = dict(epoch.rows)
    incomplete["may_read"] = [row for row in epoch.rows["may_read"] if row != ("whole", "item", "second")]
    with pytest.raises(access.Uncovered):
        access.for_role(incomplete, epoch.kinds, epoch.parents, epoch.columns, json.loads(epoch.rules),
                        epoch.witnesses, "whole")


def test_checker_requires_a_matching_role_kind_coverage_witness(epoch):
    readable, sees, full = filtered(epoch, "whole")
    [proof] = [w for w in epoch.witnesses if w["conclusion"]["relation"] == "may_read_full"]
    evidence = [{"kind": "item", "rule": proof["rule_id"], "ground": ["may_read_full", "whole", "item"]}]
    found, findings = checked(epoch, "whole", readable, sees["witnesses"], full, evidence, epoch.witnesses)
    assert "item" in found and "item__label" in found and findings == []
    for forged in ([], [{**evidence[0], "ground": ["may_read_full", "partial", "item"]}],
                   [{**evidence[0], "rule": "another_rule"}]):
        _, failures = checked(epoch, "whole", readable, sees["witnesses"], full, forged, epoch.witnesses)
        assert any(f["reason"] == "evidence_mismatch" for f in failures)
    _, failures = checked(epoch, "whole", readable, sees["witnesses"], full, evidence,
                          [w for w in epoch.witnesses if w != proof])
    assert failures
