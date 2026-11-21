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
from rezono_canon import canonical_sha256
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


def _state_rows(rows: set[tuple], keys: int) -> tuple[set[tuple], dict[tuple, str]]:
    """(key..., state, reason) of every row, and the value of every known row, from (key..., state, reason, value)."""
    states = {row[:keys + 2] for row in rows}
    known = {row[:keys]: row[keys + 2] for row in rows if row[keys] == "known"}
    return states, known


def _check_functional_outcome(
    con,
    derived: dict[str, set[tuple]],
    name: str,
    keys: int,
    expected_states: set[tuple],
    expected_known: dict[tuple, str],
) -> None:
    if any(cell is None for row in con.execute(f'SELECT * FROM "{name}"').fetchall() for cell in row):
        raise MissingRequirementLowering(f"{name}: a NULL cell in a NOT NULL functional view")
    states, known = _state_rows(derived.get(name, set()), keys)
    if states != expected_states or known != expected_known:
        raise MissingRequirementLowering(json.dumps({
            name: {
                "states_got": sorted(states),
                "states_want": sorted(expected_states),
                "known_got": sorted(known.items()),
                "known_want": sorted(expected_known.items()),
            }
        }, indent=2))


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
        "missing pattern, not_applicable when untriggered, unknown on missing trigger slot, invalid on conflict). "
        "Waits for compiler/tests/rezono/test_language_requirements.py--test_lower_requirement_to_rules_ir."
    ),
)
def test_requirement_violation_witness_cites_trigger_and_missing_pattern(tmp_path):
    directory = _write_pack(tmp_path / "witness", WITNESS_MODULE, WITNESS_FACTS)
    _, document, _, _, con, derived, explainer, manifest, read_bytes = _evaluate(directory)

    _check_functional_outcome(
        con, derived, "rack_dual_feed", 1,
        expected_states={
            ("rack-ok", "known", ""),
            ("rack-missing-b", "known", ""),
            ("rack-outside", "not_applicable", "no_match"),
            ("rack-no-flag", "unknown", "no_value"),
            ("rack-conflict", "not_applicable", "no_match"),
        },
        expected_known={
            ("rack-ok",): "true",
            ("rack-missing-b",): "false",
        },
    )

    expected_viol = {("rack-missing-b", "1", "power_feed", "at_least:1", "0")}
    if derived.get("rack_dual_feed_violation") != expected_viol:
        raise MissingRequirementLowering(
            f"rack_dual_feed_violation={sorted(derived.get('rack_dual_feed_violation', ()))}, expected={sorted(expected_viol)}"
        )

    if any(cell is None for row in con.execute('SELECT * FROM "assigned_rack_backup"').fetchall() for cell in row):
        raise MissingRequirementLowering("assigned_rack_backup: a NULL cell in a NOT NULL functional view")
    conflict_states, conflict_known = _state_rows(
        {row for row in derived.get("assigned_rack_backup", ()) if row[0] == "rack-conflict"}, 1
    )
    if conflict_states != {("rack-conflict", "invalid", "multiple_values")} or conflict_known:
        raise MissingRequirementLowering(
            f"invalid input state={sorted(conflict_states)} known={sorted(conflict_known.items())}"
        )
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
        "and unknown open_world on plain world open. "
        "Waits for compiler/tests/rezono/test_language_requirements.py--test_lower_requirement_to_rules_ir."
    ),
)
def test_requirement_unknown_without_complete_sweep(tmp_path):
    directory = _write_pack(tmp_path / "sweep", SWEEP_MODULE, SWEEP_FACTS)
    _, document, _, _, con, derived, explainer, manifest, read_bytes = _evaluate(directory)

    _check_functional_outcome(
        con, derived, "service_has_origin", 1,
        expected_states={
            ("svc-covered-missing", "known", ""),
            ("svc-uncovered-missing", "unknown", "incomplete_read"),
            ("svc-uncovered-present", "known", ""),
        },
        expected_known={
            ("svc-covered-missing",): "false",
            ("svc-uncovered-present",): "true",
        },
    )

    expected_viol = {("svc-covered-missing", "0", "origin_observation", "at_least:1", "0")}
    if derived.get("service_has_origin_violation") != expected_viol:
        raise MissingRequirementLowering(
            f"service_has_origin_violation={sorted(derived.get('service_has_origin_violation', ()))}"
        )

    _check_functional_outcome(
        con, derived, "service_has_unscoped", 1,
        expected_states={
            ("svc-covered-missing", "unknown", "open_world"),
            ("svc-uncovered-missing", "unknown", "open_world"),
            ("svc-uncovered-present", "unknown", "open_world"),
        },
        expected_known={},
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
        "unknown incomplete_read when unproven under incomplete sweeps, and not_applicable when untriggered. "
        "Waits for compiler/tests/rezono/test_language_requirements.py--test_lower_requirement_to_rules_ir."
    ),
)
def test_requirement_cardinality_bounds_and_incomplete_sweep(tmp_path):
    directory = _write_pack(tmp_path / "cardinality", CARDINALITY_MODULE, CARDINALITY_FACTS)
    _, document, _, _, con, derived, explainer, manifest, read_bytes = _evaluate(directory)

    _check_functional_outcome(
        con, derived, "service_ha", 1,
        expected_states={
            ("svc-two", "known", ""),
            ("svc-three", "known", ""),
            ("svc-five", "known", ""),
            ("svc-unswept", "unknown", "incomplete_read"),
            ("svc-standard", "not_applicable", "no_match"),
        },
        expected_known={
            ("svc-two",): "false",
            ("svc-three",): "true",
            ("svc-five",): "true",
        },
    )
    _check_functional_outcome(
        con, derived, "single_primary", 1,
        expected_states={
            ("svc-two", "known", ""),
            ("svc-three", "known", ""),
            ("svc-five", "known", ""),
            ("svc-unswept", "known", ""),
            ("svc-standard", "not_applicable", "no_match"),
        },
        expected_known={
            ("svc-two",): "true",
            ("svc-three",): "false",
            ("svc-five",): "false",
            ("svc-unswept",): "true",
        },
    )
    _check_functional_outcome(
        con, derived, "bounded_replicas", 1,
        expected_states={
            ("svc-two", "known", ""),
            ("svc-three", "known", ""),
            ("svc-five", "known", ""),
            ("svc-unswept", "unknown", "incomplete_read"),
            ("svc-standard", "not_applicable", "no_match"),
        },
        expected_known={
            ("svc-two",): "true",
            ("svc-three",): "true",
            ("svc-five",): "false",
        },
    )

    expected_violations = {
        "service_ha_violation": {
            ("svc-two", "0", "replica", "at_least:3", "2"),
        },
        "single_primary_violation": {
            ("svc-three", "0", "primary_node", "exactly:1", "2"),
            ("svc-five", "0", "primary_node", "exactly:1", "0"),
        },
        "bounded_replicas_violation": {
            ("svc-five", "0", "replica", "at_most:4", "5"),
        },
    }

    problems = []
    for name, want in expected_violations.items():
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


def _verify_bound_witness(
    explainer,
    manifest,
    read_bytes,
    document: dict,
    relation: str,
    row: tuple[str, ...],
    *,
    scope: str,
    expected_time: str,
    expected_identities: set[str],
    identity_relation: str,
    scope_relation: str,
    time_relation: str,
    forbidden_coverage_relation: str | None = None,
    required_coverage_relation: str | None = None,
) -> None:
    """Verify a checker-validated bound proof carries distinct identities, scope, time, and honest coverage."""
    proof = _verified_proof(explainer, manifest, read_bytes, document, relation, row)
    premises = [p for w in proof["witnesses"] for p in w.get("premises", [])]
    aggregates = [a for w in proof["witnesses"] for a in w.get("aggregates", [])]
    scope_key = explain.key_text([scope])

    if forbidden_coverage_relation is not None and any(
        p["row"]["relation"] == forbidden_coverage_relation for p in premises
    ):
        raise MissingRequirementLowering(
            f"{relation}{row}: proven bound on incomplete register fabricated coverage premise "
            f"{forbidden_coverage_relation}; proof={json.dumps(proof, indent=2)}"
        )
    if required_coverage_relation is not None and not any(
        p["polarity"] == "positive"
        and p["row"] == {"relation": required_coverage_relation, "key": scope_key}
        for p in premises
    ):
        raise MissingRequirementLowering(
            f"{relation}{row}: exact-count proof missing load-bearing coverage premise "
            f"{required_coverage_relation}({scope_key}); proof={json.dumps(proof, indent=2)}"
        )

    expected_count = len(expected_identities)
    matching_aggs = [
        a for a in aggregates
        if a["group_key"] == scope_key
        and a["count"] == expected_count
        and a["result"] == f"known:{expected_count}"
    ]
    if not matching_aggs:
        raise MissingRequirementLowering(
            f"{relation}{row}: missing count={expected_count} aggregate for scope {scope_key}; "
            f"aggregates={json.dumps(aggregates, indent=2)}"
        )

    agg = matching_aggs[0]
    match_rel = agg["relation"]
    contributors = sorted(r for r in explainer.rows.get(match_rel, ()) if r[0] == scope)
    expected_sha = canonical_sha256([[explain.key_text(r)] for r in contributors])
    if len(contributors) != expected_count or expected_sha != agg["contributors_sha256"]:
        raise MissingRequirementLowering(
            f"{relation}{row}: aggregate contributors mismatch on {match_rel}: "
            f"rows={contributors}, sha={expected_sha}, agg={agg}"
        )

    observed_ids = {r[1] for r in contributors}
    if observed_ids != expected_identities:
        raise MissingRequirementLowering(
            f"{relation}{row}: witness identities={sorted(observed_ids)}, expected={sorted(expected_identities)}"
        )

    for contrib in contributors:
        c_proof = _verified_proof(explainer, manifest, read_bytes, document, match_rel, contrib)
        c_premises = [
            p["row"] for w in c_proof["witnesses"] for p in w.get("premises", [])
            if p["polarity"] == "positive"
        ]
        wid = contrib[1]
        wanted_rows = (
            {"relation": identity_relation, "key": explain.key_text([wid])},
            {"relation": scope_relation, "key": explain.key_text([wid, scope])},
            {"relation": time_relation, "key": explain.key_text([wid, expected_time])},
        )
        missing = [wrow for wrow in wanted_rows if wrow not in c_premises]
        if missing:
            raise MissingRequirementLowering(
                f"{relation}{row}: witness for {contrib} missing premises {missing}; "
                f"c_premises={json.dumps(c_premises, indent=2)}"
            )


PROVEN_BOUNDS_TIME = "2026-11-21T10:00:00Z"

PROVEN_BOUNDS_MODULE = """\
rezono 1
pack minimal

enum Tier = critical | standard
enum Flag = yes | no

kind Service
  tier: Tier
  as_of: Text
kind ReplicaSweep
  service: Service

derived replica_sweep_complete(service: Service): Bool = ReplicaSweep.any(it.service = service)

kind ReplicaObservation world open, complete by replica_sweep_complete
  service: Service
  healthy: Flag
  observed_at: Text

require service_exists_replica(s: Service)
  when s.tier = critical
  exists r: ReplicaObservation where r.service = s and r.healthy = yes and r.observed_at = s.as_of

require service_at_least_one(s: Service)
  when s.tier = critical
  exists at least 1 r: ReplicaObservation where r.service = s and r.healthy = yes and r.observed_at = s.as_of

require service_ha(s: Service)
  when s.tier = critical
  exists at least 3 r: ReplicaObservation where r.service = s and r.healthy = yes and r.observed_at = s.as_of

require bounded_replicas(s: Service)
  when s.tier = critical
  exists at most 4 r: ReplicaObservation where r.service = s and r.healthy = yes and r.observed_at = s.as_of

require single_replica(s: Service)
  when s.tier = critical
  exists exactly 1 r: ReplicaObservation where r.service = s and r.healthy = yes and r.observed_at = s.as_of
"""

PROVEN_BOUNDS_FACTS = f"""\
service:
  - {{id: svc-one-unswept, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-two-unswept, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-three-unswept, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-five-unswept, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-one-swept, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
replica_sweep:
  - {{id: sw-one, service: svc-one-swept}}
replica_observation:
  - {{id: r-u1, service: svc-one-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u2a, service: svc-two-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u2b, service: svc-two-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u2c, service: svc-two-unswept, healthy: "no", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u2-stale, service: svc-two-unswept, healthy: "yes", observed_at: "2026-11-20T10:00:00Z"}}
  - {{id: r-u3a, service: svc-three-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u3b, service: svc-three-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u3c, service: svc-three-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u5a, service: svc-five-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u5b, service: svc-five-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u5c, service: svc-five-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u5d, service: svc-five-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-u5e, service: svc-five-unswept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-s1, service: svc-one-swept, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRequirementLowering,
    reason=(
        "M3: decisions/language-requirements.md: Separate proven cardinality bounds from exact "
        "counting on incomplete world-open registers (1 match proves exists and at least 1, "
        "3 distinct confirmed replicas prove at least 3, 5 prove at most 4 violated, >=2 prove "
        "exactly 1 violated, 2 for at least 3 remains unknown incomplete_read, and verified "
        "witnesses carry distinct identities, scope, time, and coverage only when load-bearing)."
    ),
)
def test_requirement_proven_bounds_vs_exact_count(tmp_path):
    directory = _write_pack(tmp_path / "proven-bounds", PROVEN_BOUNDS_MODULE, PROVEN_BOUNDS_FACTS)
    _, document, _, _, con, derived, explainer, manifest, read_bytes = _evaluate(directory)

    all_known_true = {
        ("svc-one-unswept", "known", ""),
        ("svc-two-unswept", "known", ""),
        ("svc-three-unswept", "known", ""),
        ("svc-five-unswept", "known", ""),
        ("svc-one-swept", "known", ""),
    }
    all_true_vals = {
        ("svc-one-unswept",): "true",
        ("svc-two-unswept",): "true",
        ("svc-three-unswept",): "true",
        ("svc-five-unswept",): "true",
        ("svc-one-swept",): "true",
    }

    # Case 1: 1 certain match on an incomplete register proves BOTH `exists` and `at least 1`.
    _check_functional_outcome(con, derived, "service_exists_replica", 1, all_known_true, all_true_vals)
    _check_functional_outcome(con, derived, "service_at_least_one", 1, all_known_true, all_true_vals)

    # Cases 2 & 4: 3 distinct confirmed replicas prove `at least 3` without sweep; 2 remains unknown incomplete_read.
    _check_functional_outcome(
        con, derived, "service_ha", 1,
        expected_states={
            ("svc-one-unswept", "unknown", "incomplete_read"),
            ("svc-two-unswept", "unknown", "incomplete_read"),
            ("svc-three-unswept", "known", ""),
            ("svc-five-unswept", "known", ""),
            ("svc-one-swept", "known", ""),
        },
        expected_known={
            ("svc-three-unswept",): "true",
            ("svc-five-unswept",): "true",
            ("svc-one-swept",): "false",
        },
    )

    # Case 3: 5 distinct confirmed replicas prove violation of `at most 4` without sweep; <= 4 without sweep stays unknown.
    _check_functional_outcome(
        con, derived, "bounded_replicas", 1,
        expected_states={
            ("svc-one-unswept", "unknown", "incomplete_read"),
            ("svc-two-unswept", "unknown", "incomplete_read"),
            ("svc-three-unswept", "unknown", "incomplete_read"),
            ("svc-five-unswept", "known", ""),
            ("svc-one-swept", "known", ""),
        },
        expected_known={
            ("svc-five-unswept",): "false",
            ("svc-one-swept",): "true",
        },
    )

    # Exact bound: >= 2 proves violation of `exactly 1` without sweep; `known true` requires complete sweep.
    _check_functional_outcome(
        con, derived, "single_replica", 1,
        expected_states={
            ("svc-one-unswept", "unknown", "incomplete_read"),
            ("svc-two-unswept", "known", ""),
            ("svc-three-unswept", "known", ""),
            ("svc-five-unswept", "known", ""),
            ("svc-one-swept", "known", ""),
        },
        expected_known={
            ("svc-two-unswept",): "false",
            ("svc-three-unswept",): "false",
            ("svc-five-unswept",): "false",
            ("svc-one-swept",): "true",
        },
    )

    expected_violations = {
        "service_exists_replica_violation": set(),
        "service_at_least_one_violation": set(),
        "service_ha_violation": {
            ("svc-one-swept", "0", "replica_observation", "at_least:3", "1"),
        },
        "bounded_replicas_violation": {
            ("svc-five-unswept", "0", "replica_observation", "at_most:4", "5"),
        },
        "single_replica_violation": {
            ("svc-two-unswept", "0", "replica_observation", "exactly:1", "2"),
            ("svc-three-unswept", "0", "replica_observation", "exactly:1", "3"),
            ("svc-five-unswept", "0", "replica_observation", "exactly:1", "5"),
        },
    }
    problems = []
    for name, want in expected_violations.items():
        got = derived.get(name, set())
        if got != want:
            problems.append({name: {"got": sorted(got), "want": sorted(want)}})
    if problems:
        raise MissingRequirementLowering(json.dumps(problems, indent=2))

    # Verified witnesses carrying distinct identities, scope, and time (no fabricated coverage on incomplete registers).
    obs_rels = {
        "identity_relation": "replica_observation",
        "scope_relation": "replica_observation__service",
        "time_relation": "replica_observation__observed_at",
    }
    _verify_bound_witness(
        explainer, manifest, read_bytes, document,
        "service_exists_replica", ("svc-one-unswept", "known", "", "true"),
        scope="svc-one-unswept",
        expected_time=PROVEN_BOUNDS_TIME,
        expected_identities={"r-u1"},
        forbidden_coverage_relation="replica_sweep_complete",
        **obs_rels,
    )
    _verify_bound_witness(
        explainer, manifest, read_bytes, document,
        "service_at_least_one", ("svc-one-unswept", "known", "", "true"),
        scope="svc-one-unswept",
        expected_time=PROVEN_BOUNDS_TIME,
        expected_identities={"r-u1"},
        forbidden_coverage_relation="replica_sweep_complete",
        **obs_rels,
    )
    _verify_bound_witness(
        explainer, manifest, read_bytes, document,
        "service_ha", ("svc-three-unswept", "known", "", "true"),
        scope="svc-three-unswept",
        expected_time=PROVEN_BOUNDS_TIME,
        expected_identities={"r-u3a", "r-u3b", "r-u3c"},
        forbidden_coverage_relation="replica_sweep_complete",
        **obs_rels,
    )
    _verify_bound_witness(
        explainer, manifest, read_bytes, document,
        "bounded_replicas_violation", ("svc-five-unswept", "0", "replica_observation", "at_most:4", "5"),
        scope="svc-five-unswept",
        expected_time=PROVEN_BOUNDS_TIME,
        expected_identities={"r-u5a", "r-u5b", "r-u5c", "r-u5d", "r-u5e"},
        forbidden_coverage_relation="replica_sweep_complete",
        **obs_rels,
    )
    # Exact-count witness contrast: deficit violation under complete sweep MUST cite coverage premise.
    _verify_bound_witness(
        explainer, manifest, read_bytes, document,
        "service_ha_violation", ("svc-one-swept", "0", "replica_observation", "at_least:3", "1"),
        scope="svc-one-swept",
        expected_time=PROVEN_BOUNDS_TIME,
        expected_identities={"r-s1"},
        required_coverage_relation="replica_sweep_complete",
        **obs_rels,
    )


IDENTITY_BOUNDS_MODULE = """\
rezono 1
pack minimal

enum Tier = critical | standard
enum Flag = yes | no

kind Service
  tier: Tier
  as_of: Text
kind ReplicaSweep
  service: Service

derived replica_sweep_complete(service: Service): Bool = ReplicaSweep.any(it.service = service)

kind ReplicaEntity world open, complete by replica_sweep_complete
  service: Service

kind ReplicaObservation world open, complete by replica_sweep_complete
  service: Service
  healthy: Flag
  observed_at: Text

kind IdentityClaim
  observation: ReplicaObservation
  entity: ReplicaEntity

extend r: ReplicaObservation
  derived canonical_entity: ReplicaEntity = IdentityClaim.where(observation = r).one(entity)

require canonical_service_ha(s: Service)
  when s.tier = critical
  exists at least 3 e: ReplicaEntity where e.service = s and ReplicaObservation.any(it.service = s and it.healthy = yes and it.observed_at = s.as_of and it.canonical_entity = e)

require bounded_canonical_replicas(s: Service)
  when s.tier = critical
  exists at most 2 e: ReplicaEntity where e.service = s and ReplicaObservation.any(it.service = s and it.healthy = yes and it.observed_at = s.as_of and it.canonical_entity = e)
"""

IDENTITY_BOUNDS_FACTS = f"""\
service:
  - {{id: svc-three-distinct, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-alias, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-uncanon, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: svc-conflict, tier: critical, as_of: "{PROVEN_BOUNDS_TIME}"}}
replica_sweep:
  - {{id: sw-uncanon, service: svc-uncanon}}
replica_entity:
  - {{id: ent-ok-1, service: svc-three-distinct}}
  - {{id: ent-ok-2, service: svc-three-distinct}}
  - {{id: ent-ok-3, service: svc-three-distinct}}
  - {{id: ent-al-1, service: svc-alias}}
  - {{id: ent-al-2, service: svc-alias}}
  - {{id: ent-uc-1, service: svc-uncanon}}
  - {{id: ent-uc-2, service: svc-uncanon}}
  - {{id: ent-uc-3, service: svc-uncanon}}
  - {{id: ent-cf-1, service: svc-conflict}}
  - {{id: ent-cf-2, service: svc-conflict}}
  - {{id: ent-cf-3, service: svc-conflict}}
  - {{id: ent-cf-4, service: svc-conflict}}
  - {{id: ent-cf-5, service: svc-conflict}}
replica_observation:
  - {{id: r-ok-1, service: svc-three-distinct, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-ok-2, service: svc-three-distinct, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-ok-3, service: svc-three-distinct, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-al-1, service: svc-alias, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-al-2a, service: svc-alias, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-al-2b, service: svc-alias, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-uc-1, service: svc-uncanon, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-uc-2, service: svc-uncanon, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-uc-3, service: svc-uncanon, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-cf-1, service: svc-conflict, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-cf-2, service: svc-conflict, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-cf-3, service: svc-conflict, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
  - {{id: r-cf-bad, service: svc-conflict, healthy: "yes", observed_at: "{PROVEN_BOUNDS_TIME}"}}
identity_claim:
  - {{id: ic-ok-1, observation: r-ok-1, entity: ent-ok-1}}
  - {{id: ic-ok-2, observation: r-ok-2, entity: ent-ok-2}}
  - {{id: ic-ok-3, observation: r-ok-3, entity: ent-ok-3}}
  - {{id: ic-al-1, observation: r-al-1, entity: ent-al-1}}
  - {{id: ic-al-2a, observation: r-al-2a, entity: ent-al-2}}
  - {{id: ic-al-2b, observation: r-al-2b, entity: ent-al-2}}
  - {{id: ic-uc-1, observation: r-uc-1, entity: ent-uc-1}}
  - {{id: ic-uc-2, observation: r-uc-2, entity: ent-uc-2}}
  - {{id: ic-cf-1, observation: r-cf-1, entity: ent-cf-1}}
  - {{id: ic-cf-2, observation: r-cf-2, entity: ent-cf-2}}
  - {{id: ic-cf-3, observation: r-cf-3, entity: ent-cf-3}}
  - {{id: ic-cf-bad-1, observation: r-cf-bad, entity: ent-cf-4}}
  - {{id: ic-cf-bad-2, observation: r-cf-bad, entity: ent-cf-5}}
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRequirementLowering,
    reason=(
        "M3: decisions/language-requirements.md: Enforce conflict precedence (conflicting identity "
        "claims yield invalid multiple_values even with 3 other clean replicas) and prevent "
        "double-counting duplicate/alias or uncanonicalized identities toward at least N or "
        "violating at most M."
    ),
)
def test_requirement_bound_identity_conflict_and_alias_deduplication(tmp_path):
    directory = _write_pack(tmp_path / "identity-bounds", IDENTITY_BOUNDS_MODULE, IDENTITY_BOUNDS_FACTS)
    _, _, _, _, con, derived, _, _, _ = _evaluate(directory)

    # 3 distinct canonical entities prove `at least 3` without sweep; alias duplicates (3 obs -> 2 entities)
    # remain `unknown incomplete_read`; uncanonicalized observation remains `unknown no_match`;
    # conflicting identity record yields `invalid multiple_values` (never dropped or masked).
    _check_functional_outcome(
        con, derived, "canonical_service_ha", 1,
        expected_states={
            ("svc-three-distinct", "known", ""),
            ("svc-alias", "unknown", "incomplete_read"),
            ("svc-uncanon", "unknown", "no_match"),
            ("svc-conflict", "invalid", "multiple_values"),
        },
        expected_known={
            ("svc-three-distinct",): "true",
        },
    )

    # Same deduplication & conflict rules apply to upper bounds (`at most 2`):
    # 3 distinct entities violate `at most 2`; aliases (2 entities) and uncanonicalized obs do NOT falsely violate;
    # conflicting identity stays `invalid multiple_values` with zero violation rows.
    _check_functional_outcome(
        con, derived, "bounded_canonical_replicas", 1,
        expected_states={
            ("svc-three-distinct", "known", ""),
            ("svc-alias", "unknown", "incomplete_read"),
            ("svc-uncanon", "unknown", "no_match"),
            ("svc-conflict", "invalid", "multiple_values"),
        },
        expected_known={
            ("svc-three-distinct",): "false",
        },
    )

    if derived.get("canonical_service_ha_violation"):
        raise MissingRequirementLowering(
            f"canonical_service_ha_violation must be empty, got {sorted(derived['canonical_service_ha_violation'])}"
        )
    expected_upper_viol = {("svc-three-distinct", "0", "replica_entity", "at_most:2", "3")}
    if derived.get("bounded_canonical_replicas_violation") != expected_upper_viol:
        raise MissingRequirementLowering(
            f"bounded_canonical_replicas_violation={sorted(derived.get('bounded_canonical_replicas_violation', ()))}, "
            f"expected={sorted(expected_upper_viol)}"
        )
