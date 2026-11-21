"""Behavioral lowering, four-state semantics, verified witnesses, sweep completeness,
and cardinality bounds for `rezono 1` `require` declarations
(decisions/language-requirements.md, sections 1-3 and 7)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader
import pytest

from expression_packs import ROOT, register
from rezono_checker.check import check as verify_proof
from rezono_checker.rules import load_rules as load_checker_rules
from rezono_compiler import batch, emit, explain, pack, rules, rules_sql, scenarios
from support import FIXTURE


FACT_SOURCE = (
    'default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
    'position: compiler/tests/rezono/test_language_requirements.py#FACTS}\n'
)


class MissingRequirementLowering(AssertionError):
    """`require` in rezono 1 did not lower, evaluate, or verify witnesses per decisions/language-requirements.md."""


def _validate(schema_name: str, instance: dict, target_class: str) -> list[str]:
    definition = yaml_loader.load(str(ROOT / "contracts" / schema_name), target_class=SchemaDefinition)
    validator = Validator(definition, validation_plugins=[JsonschemaValidationPlugin(closed=True)])
    return [item.message for item in validator.validate(instance, target_class).results]


def _write_pack(directory: Path, source: str, facts: str | None = None) -> Path:
    directory = Path(shutil.copytree(FIXTURE, directory))
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "requirements.rezono", folder / "requirements.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise MissingRequirementLowering(f"write-form.ts failed: {result.stderr.strip() or result.stdout.strip()}")
    if json.loads(form.read_bytes()).get("format") != "rezono.module/5":
        raise MissingRequirementLowering(f"expected rezono.module/5, got {json.loads(form.read_bytes()).get('format')}")
    if facts is not None:
        (directory / "facts").mkdir(exist_ok=True)
        (directory / "facts/case.yaml").write_text(facts, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    register(directory, {"module": "rezono/requirements.rezono", "form": "rezono/requirements.json", "layer": "facts"})
    return directory


def _compile(directory: Path):
    try:
        model = pack.read(directory)
        files = emit.compile_pack(model)
    except pack.CompileError as error:
        raise MissingRequirementLowering(str(error)) from error
    if "ir/rules.json" not in files:
        raise MissingRequirementLowering(f"no ir/rules.json among {sorted(files)}")
    document = json.loads(files["ir/rules.json"])
    bundle = json.loads(files["bundle/schema-bundle.json"])
    try:
        prog = rules.load(document)
    except rules.IRError as error:
        raise MissingRequirementLowering(f"rules.load failed: {error}") from error
    return model, files, document, bundle, prog


def _evaluate(directory: Path):
    model, files, document, bundle, prog = _compile(directory)
    rows = dict(scenarios.states(model, directory))["0-case"]
    con, _, _ = batch.run(model, prog, rows)
    derived = batch.read(con, prog)
    all_rows = batch.read(con, prog, prog.base_used() + prog.calc_inputs()) | derived
    explainer = explain.Explainer(prog, all_rows, batch.witnesses(con, prog))
    snaps = {r: explainer.snapshot(r).encode("utf-8") for r in sorted(prog.relations)}
    manifest = {
        "id": "0-case",
        "snapshots": [
            {
                "relation": r,
                "role": "all",
                "complete": True,
                "uri": r,
                "format": "json",
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for r, data in snaps.items()
        ],
    }
    return model, document, bundle, prog, con, derived, explainer, manifest, snaps.__getitem__


def _verified_proof(explainer, manifest, read_bytes, document, relation: str, row: tuple[str, ...]) -> dict:
    proof = explainer.proof(relation, row, "0-case")
    report = verify_proof(proof, manifest, load_checker_rules(document), read_bytes)
    if not report["valid"] or report["findings"]:
        raise MissingRequirementLowering(f"checker rejected proof for {relation}{row}: {report['findings']}")
    return proof


def _refusal(directory: Path) -> str | None:
    try:
        emit.compile_pack(pack.read(directory))
    except pack.CompileError as error:
        return " ".join([str(error), *(f"{d.code} {d.message}" for d in getattr(error, "diagnostics", ()))])
    return None


LOWERING_MODULE = """\
rezono 1
pack minimal

enum Flag = yes | no
enum Bus = bus_a | bus_b

kind Rack
  in_cage: Flag
kind PowerFeed
  rack: Rack
  bus: Bus
kind Conclusion
kind Witness
  conclusion: Conclusion

require rack_dual_feed(r: Rack)
  when r.in_cage = yes
  exists feed_a: PowerFeed where feed_a.rack = r and feed_a.bus = bus_a
  exists feed_b: PowerFeed where feed_b.rack = r and feed_b.bus = bus_b
  means "{$r} in cage must have both feed A and feed B." @ dc-policy#power-1

require conclusion_has_witness(c: Conclusion) invariant
  exists w: Witness where w.conclusion = c
"""

DUAL_FEED_SENTENCE = "{$r} in cage must have both feed A and feed B."
DUAL_FEED_SOURCE = "dc-policy#power-1"

OPEN_TRIGGER_MODULE = """\
rezono 1
pack minimal

kind OpenRack world open
kind PowerFeed
  rack: OpenRack

require open_rack_feed(r: OpenRack)
  exists f: PowerFeed where f.rack = r
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRequirementLowering,
    reason=(
        "M3: decisions/language-requirements.md: Lower rezono 1 require declarations directly "
        "into rezono.rules/2 with functional outcome relation, derived violation relation, "
        "invariant flag, means/@ bundle metadata, Feldera co-located view, and functional_open_domain refusal"
    ),
)
def test_lower_requirement_to_rules_ir(tmp_path):
    directory = _write_pack(tmp_path / "lowering", LOWERING_MODULE)
    assert not list(directory.rglob("*.dl"))
    _, _, document, bundle, prog = _compile(directory)

    problems: list = []
    if document.get("format") != "rezono.rules/2":
        problems.append({"format": document.get("format")})
    if errors := _validate("rules.yaml", document, "RuleProgram"):
        problems.append({"contracts/rules.yaml": errors[:5]})
    if errors := _validate("bundle.yaml", bundle, "Bundle"):
        problems.append({"contracts/bundle.yaml": errors[:5]})

    relations = {rel["name"]: rel for rel in document.get("relations", [])}

    for name, domain, is_invariant in (
        ("rack_dual_feed", "rack", False),
        ("conclusion_has_witness", "conclusion", True),
    ):
        outcome = relations.get(name)
        if outcome is None:
            problems.append({"missing_outcome": name, "relations": sorted(relations)})
        elif (
            outcome.get("role") != "functional"
            or outcome.get("domain") != domain
            or outcome.get("value") != {"name": "value", "type": "boolean"}
            or outcome.get("world", "closed") != "closed"
            or outcome.get("conflict_policy") != "publish"
            or len(outcome.get("key", [])) != 1
        ):
            problems.append({f"outcome_{name}": outcome})

        viol_name = f"{name}_violation"
        viol = relations.get(viol_name)
        if viol is None:
            problems.append({"missing_violation": viol_name, "relations": sorted(relations)})
        else:
            key_cols = [(c["name"], c["type"]) for c in viol.get("key", [])]
            if (
                viol.get("role") != "derived"
                or viol.get("world", "closed") != "closed"
                or bool(viol.get("invariant", False)) != is_invariant
                or key_cols[1:] != [
                    ("clause", "integer"),
                    ("target", "string"),
                    ("bound", "string"),
                    ("observed", "integer"),
                ]
            ):
                problems.append({f"violation_{viol_name}": viol})

    feldera_sql = rules_sql.feldera(prog, witnesses="none")
    for name in ("rack_dual_feed", "conclusion_has_witness"):
        if (
            len(re.findall(rf'CREATE MATERIALIZED VIEW\s+"?{name}\b', feldera_sql)) != 1
            or re.search(rf'DECLARE RECURSIVE VIEW\s+"?{name}\b', feldera_sql)
        ):
            problems.append({"feldera_view": name})

    [messages] = [entry["resource"].splitlines() for entry in bundle.get("messages", []) if entry["lang"] == "nl"]
    dual_rules = [entry for entry in bundle.get("rules", []) if entry.get("relation") in {"rack_dual_feed", "rack_dual_feed_violation"}]
    if not dual_rules:
        problems.append({"missing_bundle_rules": [e.get("relation") for e in bundle.get("rules", [])]})
    elif not any(
        entry.get("source") == DUAL_FEED_SOURCE
        and f"{entry['message']} = {{{{{DUAL_FEED_SENTENCE}}}}}" in messages
        for entry in dual_rules
    ):
        problems.append({"missing_means_or_source": dual_rules, "messages": [m for m in messages if m.startswith("rule.")]})

    refusal = _refusal(_write_pack(tmp_path / "open-trigger", OPEN_TRIGGER_MODULE))
    if refusal is None or "functional_open_domain" not in refusal:
        problems.append({"open_trigger_refusal": refusal})

    if problems:
        raise MissingRequirementLowering(json.dumps(problems, indent=2, default=str))


WITNESS_MODULE = """\
rezono 1
pack minimal

enum Flag = yes | no
enum Bus = bus_a | bus_b

kind Rack
  in_cage: Flag
kind PowerFeed
  rack: Rack
  bus: Bus
kind CageAssignment
  rack: Rack
  cage: Text
kind BackupFeed
  rack: Rack

extend r: Rack
  derived assigned_cage: Text? = CageAssignment.where(rack = r).one(cage)

require rack_dual_feed(r: Rack)
  when r.in_cage = yes
  exists feed_a: PowerFeed where feed_a.rack = r and feed_a.bus = bus_a
  exists feed_b: PowerFeed where feed_b.rack = r and feed_b.bus = bus_b

require assigned_rack_backup(r: Rack)
  when r.assigned_cage = "cage-1"
  exists b: BackupFeed where b.rack = r
"""

WITNESS_FACTS = """\
rack:
  - {id: rack-ok, in_cage: "yes"}
  - {id: rack-missing-b, in_cage: "yes"}
  - {id: rack-outside, in_cage: "no"}
  - {id: rack-no-flag}
  - {id: rack-conflict, in_cage: "no"}
power_feed:
  - {id: pf-ok-a, rack: rack-ok, bus: bus_a}
  - {id: pf-ok-b, rack: rack-ok, bus: bus_b}
  - {id: pf-mb-a, rack: rack-missing-b, bus: bus_a}
cage_assignment:
  - {id: ca-1, rack: rack-conflict, cage: cage-1}
  - {id: ca-2, rack: rack-conflict, cage: cage-2}
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRequirementLowering,
    reason=(
        "M3: decisions/language-requirements.md: Evaluate require over closed kinds across all four "
        "states (known satisfied, known violated with checker-verified witness citing both trigger and "
        "missing pattern, not_applicable when untriggered, unknown on missing trigger slot, invalid on conflict)"
    ),
)
def test_requirement_violation_witness_cites_trigger_and_missing_pattern(tmp_path):
    directory = _write_pack(tmp_path / "witness", WITNESS_MODULE, WITNESS_FACTS)
    _, document, _, _, _, derived, explainer, manifest, read_bytes = _evaluate(directory)

    expected_outcome = {
        ("rack-ok", "known", "", "true"),
        ("rack-missing-b", "known", "", "false"),
        ("rack-outside", "not_applicable", "no_match", ""),
        ("rack-no-flag", "unknown", "no_value", ""),
        ("rack-conflict", "not_applicable", "no_match", ""),
    }
    if derived.get("rack_dual_feed") != expected_outcome:
        raise MissingRequirementLowering(
            f"rack_dual_feed={sorted(derived.get('rack_dual_feed', ()))}, expected={sorted(expected_outcome)}"
        )

    expected_viol = {("rack-missing-b", "1", "power_feed", "at_least:1", "0")}
    if derived.get("rack_dual_feed_violation") != expected_viol:
        raise MissingRequirementLowering(
            f"rack_dual_feed_violation={sorted(derived.get('rack_dual_feed_violation', ()))}, expected={sorted(expected_viol)}"
        )

    conflict_rows = {row for row in derived.get("assigned_rack_backup", ()) if row[0] == "rack-conflict"}
    if conflict_rows != {("rack-conflict", "invalid", "multiple_values", "")}:
        raise MissingRequirementLowering(f"invalid input state={sorted(conflict_rows)}")
    if any(row[0] == "rack-conflict" for row in derived.get("assigned_rack_backup_violation", ())):
        raise MissingRequirementLowering("invalid input must not emit a violation row")

    proof = _verified_proof(
        explainer, manifest, read_bytes, document,
        "rack_dual_feed_violation",
        ("rack-missing-b", "1", "power_feed", "at_least:1", "0"),
    )
    premises = [p for w in proof["witnesses"] for p in w.get("premises", [])]
    aggregates = [a for w in proof["witnesses"] for a in w.get("aggregates", [])]

    cites_trigger = (
        any(p["polarity"] == "positive" and p["row"] == {"relation": "rack", "key": '["rack-missing-b"]'} for p in premises)
        and any(
            p["polarity"] == "positive"
            and p["row"] == {"relation": "rack__in_cage", "key": '["rack-missing-b","yes"]'}
            for p in premises
        )
    )
    cites_missing = (
        any(p["polarity"] == "negative" and "rack-missing-b" in p["row"]["key"] for p in premises)
        or any(a["count"] == 0 and "rack-missing-b" in a["group_key"] for a in aggregates)
    )
    if not cites_trigger or not cites_missing:
        raise MissingRequirementLowering(
            f"witness must cite both trigger and missing pattern; proof={json.dumps(proof, indent=2)}"
        )


SWEEP_MODULE = """\
rezono 1
pack minimal

kind Service
kind SweepReceipt
  service: Service

derived sweep_complete(service: Service): Bool = SweepReceipt.any(it.service = service)

kind OriginObservation world open, complete by sweep_complete
  service: Service
kind UnscopedObservation world open
  service: Service

require service_has_origin(s: Service)
  exists o: OriginObservation where o.service = s

require service_has_unscoped(s: Service)
  exists u: UnscopedObservation where u.service = s
"""

SWEEP_FACTS = """\
service:
  - {id: svc-covered-missing}
  - {id: svc-uncovered-missing}
  - {id: svc-uncovered-present}
sweep_receipt:
  - {id: rcpt-1, service: svc-covered-missing}
origin_observation:
  - {id: obs-1, service: svc-uncovered-present}
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRequirementLowering,
    reason=(
        "M3: decisions/language-requirements.md: Evaluate require over an observed world-open target "
        "to unknown incomplete_read without a complete sweep (never false pass or false violation), "
        "known true when positively witnessed, known false with coverage witness once complete sweep holds, "
        "and unknown open_world on plain world open"
    ),
)
def test_requirement_unknown_without_complete_sweep(tmp_path):
    directory = _write_pack(tmp_path / "sweep", SWEEP_MODULE, SWEEP_FACTS)
    _, document, _, _, _, derived, explainer, manifest, read_bytes = _evaluate(directory)

    expected_origin = {
        ("svc-covered-missing", "known", "", "false"),
        ("svc-uncovered-missing", "unknown", "incomplete_read", ""),
        ("svc-uncovered-present", "known", "", "true"),
    }
    if derived.get("service_has_origin") != expected_origin:
        raise MissingRequirementLowering(
            f"service_has_origin={sorted(derived.get('service_has_origin', ()))}, expected={sorted(expected_origin)}"
        )

    expected_viol = {("svc-covered-missing", "0", "origin_observation", "at_least:1", "0")}
    if derived.get("service_has_origin_violation") != expected_viol:
        raise MissingRequirementLowering(
            f"service_has_origin_violation={sorted(derived.get('service_has_origin_violation', ()))}"
        )

    expected_unscoped = {
        ("svc-covered-missing", "unknown", "open_world", ""),
        ("svc-uncovered-missing", "unknown", "open_world", ""),
        ("svc-uncovered-present", "unknown", "open_world", ""),
    }
    if derived.get("service_has_unscoped") != expected_unscoped:
        raise MissingRequirementLowering(
            f"service_has_unscoped={sorted(derived.get('service_has_unscoped', ()))}"
        )
    if derived.get("service_has_unscoped_violation"):
        raise MissingRequirementLowering(
            f"plain world open must never emit violation: {sorted(derived['service_has_unscoped_violation'])}"
        )

    proof = _verified_proof(
        explainer, manifest, read_bytes, document,
        "service_has_origin_violation",
        ("svc-covered-missing", "0", "origin_observation", "at_least:1", "0"),
    )
    premises = [p for w in proof["witnesses"] for p in w.get("premises", [])]
    if not any(
        p["polarity"] == "positive"
        and p["row"] == {"relation": "sweep_complete", "key": '["svc-covered-missing"]'}
        for p in premises
    ):
        raise MissingRequirementLowering(
            f"violation over complete-by kind must cite coverage premise sweep_complete; proof={json.dumps(proof, indent=2)}"
        )


CARDINALITY_MODULE = """\
rezono 1
pack minimal

enum Tier = critical | standard
enum Flag = yes | no

kind Service
  tier: Tier
kind ReplicaSweep
  service: Service

derived replica_sweep_complete(service: Service): Bool = ReplicaSweep.any(it.service = service)

kind Replica world open, complete by replica_sweep_complete
  service: Service
  healthy: Flag
kind PrimaryNode
  service: Service
  role: Text

require service_ha(s: Service)
  when s.tier = critical
  exists at least 3 r: Replica where r.service = s and r.healthy = yes

require single_primary(s: Service)
  when s.tier = critical
  exists exactly 1 n: PrimaryNode where n.service = s and n.role = "primary"

require bounded_replicas(s: Service)
  when s.tier = critical
  exists at most 4 r: Replica where r.service = s and r.healthy = yes
"""

CARDINALITY_FACTS = """\
service:
  - {id: svc-two, tier: critical}
  - {id: svc-three, tier: critical}
  - {id: svc-five, tier: critical}
  - {id: svc-unswept, tier: critical}
  - {id: svc-standard, tier: standard}
replica_sweep:
  - {id: sw-1, service: svc-two}
  - {id: sw-2, service: svc-three}
  - {id: sw-3, service: svc-five}
  - {id: sw-4, service: svc-standard}
replica:
  - {id: r-2a, service: svc-two, healthy: "yes"}
  - {id: r-2b, service: svc-two, healthy: "yes"}
  - {id: r-2c, service: svc-two, healthy: "no"}
  - {id: r-3a, service: svc-three, healthy: "yes"}
  - {id: r-3b, service: svc-three, healthy: "yes"}
  - {id: r-3c, service: svc-three, healthy: "yes"}
  - {id: r-5a, service: svc-five, healthy: "yes"}
  - {id: r-5b, service: svc-five, healthy: "yes"}
  - {id: r-5c, service: svc-five, healthy: "yes"}
  - {id: r-5d, service: svc-five, healthy: "yes"}
  - {id: r-5e, service: svc-five, healthy: "yes"}
  - {id: r-ua, service: svc-unswept, healthy: "yes"}
  - {id: r-ub, service: svc-unswept, healthy: "yes"}
primary_node:
  - {id: pn-2, service: svc-two, role: primary}
  - {id: pn-3a, service: svc-three, role: primary}
  - {id: pn-3b, service: svc-three, role: primary}
  - {id: pn-u, service: svc-unswept, role: primary}
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRequirementLowering,
    reason=(
        "M3: decisions/language-requirements.md: Enforce cardinality bounds (at least N, at most N, "
        "exactly N) with observed-count witnesses under complete sweeps, pass when in bounds, "
        "unknown incomplete_read under incomplete sweeps, and not_applicable when untriggered"
    ),
)
def test_requirement_cardinality_bounds_and_incomplete_sweep(tmp_path):
    directory = _write_pack(tmp_path / "cardinality", CARDINALITY_MODULE, CARDINALITY_FACTS)
    _, document, _, _, _, derived, explainer, manifest, read_bytes = _evaluate(directory)

    expected = {
        "service_ha": {
            ("svc-two", "known", "", "false"),
            ("svc-three", "known", "", "true"),
            ("svc-five", "known", "", "true"),
            ("svc-unswept", "unknown", "incomplete_read", ""),
            ("svc-standard", "not_applicable", "no_match", ""),
        },
        "service_ha_violation": {
            ("svc-two", "0", "replica", "at_least:3", "2"),
        },
        "single_primary": {
            ("svc-two", "known", "", "true"),
            ("svc-three", "known", "", "false"),
            ("svc-five", "known", "", "false"),
            ("svc-unswept", "known", "", "true"),
            ("svc-standard", "not_applicable", "no_match", ""),
        },
        "single_primary_violation": {
            ("svc-three", "0", "primary_node", "exactly:1", "2"),
            ("svc-five", "0", "primary_node", "exactly:1", "0"),
        },
        "bounded_replicas": {
            ("svc-two", "known", "", "true"),
            ("svc-three", "known", "", "true"),
            ("svc-five", "known", "", "false"),
            ("svc-unswept", "unknown", "incomplete_read", ""),
            ("svc-standard", "not_applicable", "no_match", ""),
        },
        "bounded_replicas_violation": {
            ("svc-five", "0", "replica", "at_most:4", "5"),
        },
    }

    problems = []
    for name, want in expected.items():
        got = derived.get(name, set())
        if got != want:
            problems.append({name: {"got": sorted(got), "want": sorted(want)}})
    if problems:
        raise MissingRequirementLowering(json.dumps(problems, indent=2))

    proof = _verified_proof(
        explainer, manifest, read_bytes, document,
        "service_ha_violation",
        ("svc-two", "0", "replica", "at_least:3", "2"),
    )
    premises = [p for w in proof["witnesses"] for p in w.get("premises", [])]
    aggregates = [a for w in proof["witnesses"] for a in w.get("aggregates", [])]
    if not any(
        p["polarity"] == "positive"
        and p["row"] == {"relation": "replica_sweep_complete", "key": '["svc-two"]'}
        for p in premises
    ):
        raise MissingRequirementLowering(f"service_ha violation proof missing coverage premise: {proof}")
    if not any(a["count"] == 2 and "svc-two" in a["group_key"] for a in aggregates):
        raise MissingRequirementLowering(f"service_ha violation proof missing count=2 aggregate: {proof}")
