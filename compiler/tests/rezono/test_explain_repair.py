"""Behavioral tests for the `repair` explanation question in `std-explain` (Layer 1: chase completion)
(decisions/explain-repair.md, sections 1, 2, and 4)."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader
import pytest
import yaml

from expression_packs import ROOT, register
from rezono_checker.check import check as verify_proof
from rezono_checker.rules import load_rules as load_checker_rules
from rezono_compiler import modules, pack
from rezono_publisher import batch as publisher_batch
from rezono_publisher import publish, store, views
from support import FIXTURE


STD_EXPLAIN = ROOT / "packs" / "std-explain"
KNOWLEDGE_TIME = "2026-11-21T00:00:00Z"
ROLES = {"checker": "complete", "viewer": "may_read"}
FACT_SOURCE = (
    'default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
    'position: compiler/tests/rezono/test_explain_repair.py#FACTS}\n'
)


class MissingExplainRepair(AssertionError):
    """`std-explain` `repair` Layer 1 chase completion or termination refusal is not implemented per decisions/explain-repair.md."""


def _validate(schema_name: str, instance: dict, target_class: str) -> list[str]:
    definition = yaml_loader.load(str(ROOT / "contracts" / schema_name), target_class=SchemaDefinition)
    validator = Validator(definition, validation_plugins=[JsonschemaValidationPlugin(closed=True)])
    return [item.message for item in validator.validate(instance, target_class).results]


def _import_required(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        raise MissingExplainRepair(f"missing module {module_name}: {error}") from error


def _write_pack(
    directory: Path,
    source: str,
    *,
    facts: str | None = None,
    access_rules: str | None = None,
    import_std_explain: bool = False,
) -> Path:
    directory = Path(shutil.copytree(FIXTURE, directory))
    if import_std_explain:
        meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
        meta["imports"] = [
            {
                "name": "std-explain",
                "path": str(STD_EXPLAIN),
                "sha256": modules.pack_hash(STD_EXPLAIN),
            }
        ]
        (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "repair_case.rezono", folder / "repair_case.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise MissingExplainRepair(f"write-form.ts failed: {result.stderr.strip() or result.stdout.strip()}")
    if json.loads(form.read_bytes()).get("format") != "rezono.module/5":
        raise MissingExplainRepair(f"expected rezono.module/5, got {json.loads(form.read_bytes()).get('format')}")
    if facts is not None:
        (directory / "facts").mkdir(exist_ok=True)
        (directory / "facts/case.yaml").write_text(facts, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    if access_rules is not None:
        (directory / "rules").mkdir(exist_ok=True)
        (directory / "rules/access.dl").write_text(access_rules, encoding="utf-8", newline="\n")
    register(directory, {"module": "rezono/repair_case.rezono", "form": "rezono/repair_case.json", "layer": "facts"})
    return directory


def _check_std_explain_declares_repair() -> None:
    doc = yaml.safe_load((STD_EXPLAIN / "questions.yaml").read_text(encoding="utf-8")) or {}
    by_term = {q["term"]: q for q in doc.get("questions", []) if isinstance(q, dict) and "term" in q}
    question = by_term.get("repair")
    if question is None:
        raise MissingExplainRepair(f"packs/std-explain/questions.yaml does not declare 'repair': {sorted(by_term)}")
    if (
        question.get("start") != "present"
        or question.get("answer") != "repair"
        or not any(isinstance(step, dict) and step.get("suppose") == "repair" for step in question.get("steps", []))
    ):
        raise MissingExplainRepair(f"unexpected std-explain repair question definition: {question}")
    bundled_question = {
        "term": question["term"],
        "start": question["start"],
        "applies_to": question.get("applies_to", {}),
        "steps": [
            ({"suppose": {"delta": s["suppose"]}} if "suppose" in s else {"trace": {**s["trace"], "depth": str(s["trace"]["depth"])}})
            for s in question["steps"]
        ],
        "answer": question["answer"],
        "limit": question["limit"],
    }
    if errors := _validate("explain.yaml", bundled_question, "Question"):
        raise MissingExplainRepair(f"contracts/explain.yaml rejected std-explain repair Question: {errors[:5]}")
    for lang in ("en", "nl"):
        text = (STD_EXPLAIN / "messages" / f"{lang}.mf2").read_text(encoding="utf-8")
        for key in ("explain.repair", "explain.repair.question"):
            if f"\n{key} = " not in text:
                raise MissingExplainRepair(f"packs/std-explain/messages/{lang}.mf2 missing {key}")


POWER_REPAIR_MODULE = """\
rezono 1
pack minimal

enum Bus = bus_a | bus_b

kind Rack
kind PowerSupply
  rack: Rack
  bus: Bus
  serial: Text

require rack_dual_power(r: Rack)
  exists ps_a: PowerSupply where ps_a.rack = r and ps_a.bus = bus_a
  exists ps_b: PowerSupply where ps_b.rack = r and ps_b.bus = bus_b
  means "{$r} must have both power supply A and power supply B." @ policy#power-redundancy
"""

POWER_REPAIR_FACTS = """\
rack:
  - {id: rack-b-only}
  - {id: rack-both}
power_supply:
  - {id: ps-1, rack: rack-b-only, bus: bus_b, serial: "SN-B1"}
  - {id: ps-2a, rack: rack-both, bus: bus_a, serial: "SN-A2"}
  - {id: ps-2b, rack: rack-both, bus: bus_b, serial: "SN-B2"}
"""

POWER_ACCESS_RULES = """\
.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "rack", r) :- rack(r).
may_read("viewer", "power_supply", ps) :- power_supply(ps).
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingExplainRepair,
    reason=(
        "extra: decisions/explain-repair.md: Derive minimal additive chase repair for an unmet "
        "require declaration (rack with only power supply B proposes power supply A with unknown "
        "placeholder slot), replay via suppose, verify proof with rezono_checker, and return no "
        "repair when both supplies already exist. "
        "Waits for compiler/tests/rezono/test_language_requirements.py--test_requirement_violation_witness_cites_trigger_and_missing_pattern."
    ),
)
def test_repair_chase_proposes_missing_power_supply_with_unknown_and_verifies_via_suppose(tmp_path):
    _check_std_explain_declares_repair()
    repair_mod = _import_required("rezono_publisher.repair")
    if not hasattr(repair_mod, "repair"):
        raise MissingExplainRepair("rezono_publisher.repair.repair is not defined")

    pack_dir = _write_pack(
        tmp_path / "power-repair",
        POWER_REPAIR_MODULE,
        facts=POWER_REPAIR_FACTS,
        access_rules=POWER_ACCESS_RULES,
        import_std_explain=True,
    )
    facts_before = (pack_dir / "facts" / "case.yaml").read_bytes()

    st = store.FileStore(tmp_path / "store")
    try:
        epoch = publisher_batch.epoch(
            pack_dir,
            epoch=1,
            knowledge_time=KNOWLEDGE_TIME,
            sources=[("facts", "1")],
        )
        base_manifest = publish.publish(epoch, st, ROLES)
    except Exception as error:
        raise MissingExplainRepair(f"failed to publish base pack for repair test: {error}") from error
    if base_manifest["id"] != "m-1":
        raise MissingExplainRepair(f"expected base manifest m-1, got {base_manifest['id']}")

    answer = repair_mod.repair(pack_dir, st, "m-1", "viewer", "rack_dual_power", ["rack-b-only"])

    problems: list = []
    if errors := _validate("explain.yaml", answer, "Answer"):
        problems.append({"contracts/explain.yaml": errors[:5]})
    if (
        answer.get("format") != "rezono.answer/1"
        or answer.get("question") != "repair"
        or answer.get("computed") is not True
        or answer.get("not_computed") is not None
    ):
        problems.append({"answer_header": {k: answer.get(k) for k in ("format", "question", "computed", "not_computed")}})

    rep = answer.get("repair")
    if not isinstance(rep, dict) or rep.get("needed") is not True or rep.get("cut") is not False:
        problems.append({"repair_block": rep})
    proposals = rep.get("proposals", []) if isinstance(rep, dict) else []
    if len(proposals) != 1:
        problems.append({"proposal_count": len(proposals), "proposals": proposals})
    if problems:
        raise MissingExplainRepair(json.dumps(problems, indent=2, default=str))

    prop = proposals[0]
    delta = prop.get("delta")
    if not isinstance(delta, dict) or (errors := _validate("delta.yaml", delta, "Delta")):
        raise MissingExplainRepair(f"proposal delta invalid: {errors if isinstance(delta, dict) else delta}")
    changes = delta.get("changes", [])
    if len(changes) != 1:
        raise MissingExplainRepair(f"expected minimal 1-change repair delta, got {changes}")
    ch = changes[0]
    fresh_key = ch.get("key")
    values = ch.get("values") or {}
    if (
        ch.get("op") != "insert"
        or ch.get("kind") != "power_supply"
        or not isinstance(fresh_key, str)
        or not fresh_key
        or fresh_key in {"ps-1", "ps-2a", "ps-2b"}
        or values.get("rack") != "rack-b-only"
        or values.get("bus") != "bus_a"
        or "serial" in values
    ):
        raise MissingExplainRepair(f"unexpected minimal repair change (must add bus_a without fabricating serial): {ch}")

    additions = prop.get("additions", [])
    if len(additions) != 1:
        raise MissingExplainRepair(f"expected 1 RepairAddition, got {additions}")
    add = additions[0]
    slots = add.get("slots") or {}
    if (
        add.get("kind") != "power_supply"
        or add.get("key") != fresh_key
        or add.get("key_unknown") is not True
        or slots.get("rack") != {"state": "known", "value": "rack-b-only"}
        or slots.get("bus") != {"state": "known", "value": "bus_a"}
        or slots.get("serial") != {"state": "unknown", "reason": "to_be_filled"}
    ):
        raise MissingExplainRepair(f"expected explicit unknown slot and placeholder key in RepairAddition: {add}")

    sup = prop.get("supposition")
    if (
        not isinstance(sup, dict)
        or sup.get("format") != "rezono.supposition/1"
        or sup.get("base_manifest") != "m-1"
        or not str(sup.get("manifest", "")).startswith("p-local-")
        or sup.get("withheld") is not None
    ):
        raise MissingExplainRepair(f"proposal must be replayed via local suppose: {sup}")
    diff_rows = sup.get("rows", [])
    removed_viol = any(
        r.get("relation") == "rack_dual_power_violation"
        and r.get("weight") == -1
        and (r.get("key") or [None])[0] == "rack-b-only"
        for r in diff_rows
    )
    holds_now = any(
        r.get("relation") == "rack_dual_power"
        and r.get("weight") == 1
        and r.get("key") == ["rack-b-only", "known", "", "true"]
        for r in diff_rows
    )
    added_bus_a = any(
        r.get("relation") == "power_supply__bus"
        and r.get("weight") == 1
        and r.get("key") == [fresh_key, "bus_a"]
        for r in diff_rows
    )
    fabricated_serial = any(
        r.get("relation") == "power_supply__serial"
        and r.get("weight") == 1
        and (r.get("key") or [None])[0] == fresh_key
        for r in diff_rows
    )
    if not removed_viol or not holds_now or not added_bus_a or fabricated_serial:
        raise MissingExplainRepair(
            f"suppose diff mismatch: removed_viol={removed_viol} holds_now={holds_now} "
            f"added_bus_a={added_bus_a} fabricated_serial={fabricated_serial} rows={diff_rows}"
        )

    if prop.get("verified") is not True:
        raise MissingExplainRepair(f"fail-closed violation: proposal returned with verified={prop.get('verified')!r}")
    witness = prop.get("witness")
    if not isinstance(witness, dict):
        raise MissingExplainRepair(f"missing checker-verified proof witness on proposal: {prop}")

    sup_mid = sup["manifest"]
    sup_manifest = json.loads(st.get(f"minimal/manifests/{sup_mid}.json"))
    rules_entry = next(c for c in sup_manifest["compiled"] if c["file"] == "ir/rules.json")
    rules_doc = json.loads(views._get(st, views.key_of(rules_entry["uri"]), rules_entry["sha256"]))
    snap_by_uri = {s["uri"]: s["sha256"] for s in sup_manifest["snapshots"]}

    def read_bytes(uri: str) -> bytes:
        return views._get(st, views.key_of(uri), snap_by_uri[uri])

    report = verify_proof(witness, sup_manifest, load_checker_rules(rules_doc), read_bytes)
    if not report["valid"] or report["findings"]:
        raise MissingExplainRepair(f"rezono_checker rejected repair witness: {report}")
    if not any(
        w.get("conclusion") == {"relation": "rack_dual_power", "key": '["rack-b-only","known","","true"]'}
        for w in witness.get("witnesses", [])
    ):
        raise MissingExplainRepair(f"witness does not prove rack_dual_power(rack-b-only) = known true: {witness}")

    if (pack_dir / "facts" / "case.yaml").read_bytes() != facts_before:
        raise MissingExplainRepair("repair/suppose mutated the original pack on disk")

    # Counterexample: rack-both already has both power supply A and power supply B -> no repair needed.
    noop = repair_mod.repair(pack_dir, st, "m-1", "viewer", "rack_dual_power", ["rack-both"])
    if errors := _validate("explain.yaml", noop, "Answer"):
        raise MissingExplainRepair(f"noop answer failed contracts/explain.yaml: {errors[:5]}")
    noop_rep = noop.get("repair")
    if (
        noop.get("question") != "repair"
        or noop.get("computed") is not True
        or noop.get("not_computed") is not None
        or not isinstance(noop_rep, dict)
        or noop_rep.get("needed") is not False
        or noop_rep.get("proposals") != []
    ):
        raise MissingExplainRepair(f"rack with both supplies must require no repair, got: {noop}")


CYCLIC_SELF_MODULE = """\
rezono 1
pack minimal

kind Node
  backup_of: Node?

require node_has_backup(n: Node)
  exists b: Node where b != n and b.backup_of = n
  means "Every {$n} must have a distinct backup node." @ policy#node-backup
"""

CYCLIC_MUTUAL_MODULE = """\
rezono 1
pack minimal

kind PrimaryUnit
  paired_standby: StandbyUnit?
kind StandbyUnit
  paired_primary: PrimaryUnit?

require primary_has_standby(p: PrimaryUnit)
  exists s: StandbyUnit where s.paired_primary = p

require standby_has_primary(s: StandbyUnit)
  exists p: PrimaryUnit where p.paired_standby = s
"""

ACYCLIC_CHAIN_MODULE = """\
rezono 1
pack minimal

enum Bus = bus_a | bus_b

kind Rack
kind PowerSupply
  rack: Rack
  bus: Bus
kind FeedPort
  supply: PowerSupply

require rack_dual_power(r: Rack)
  exists ps_a: PowerSupply where ps_a.rack = r and ps_a.bus = bus_a
  exists ps_b: PowerSupply where ps_b.rack = r and ps_b.bus = bus_b

require supply_has_port(ps: PowerSupply)
  exists port: FeedPort where port.supply = ps
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingExplainRepair,
    reason=(
        "extra: decisions/explain-repair.md: Refuse a cyclic existential require declaration whose "
        "chase does not terminate (each Node requires a distinct backup Node) with chase_non_terminating, "
        "while accepting an acyclic terminating require declaration. "
        "Waits for compiler/tests/rezono/test_language_requirements.py--test_lower_requirement_to_rules_ir."
    ),
)
def test_repair_chase_refuses_cyclic_existential_requirement_and_accepts_acyclic(tmp_path):
    repair_compiler = _import_required("rezono_compiler.repair")
    check_term = getattr(repair_compiler, "check_chase_termination", None)
    term_error = getattr(repair_compiler, "ChaseTerminationError", None)
    if check_term is None or term_error is None or not issubclass(term_error, pack.CompileError):
        raise MissingExplainRepair(
            "rezono_compiler.repair must expose check_chase_termination and ChaseTerminationError(CompileError)"
        )

    for label, source, expected_names in (
        ("self-cycle", CYCLIC_SELF_MODULE, ("node_has_backup", "node")),
        ("mutual-cycle", CYCLIC_MUTUAL_MODULE, ("primary_has_standby", "standby_has_primary")),
    ):
        directory = _write_pack(tmp_path / label, source)
        try:
            model = pack.read(directory)
            check_term(model)
        except term_error as error:
            text = " ".join(
                [str(error), *(f"{d.code} {d.message}" for d in getattr(error, "diagnostics", ()))]
            ).lower()
            if "chase_non_terminating" not in text or not any(name in text for name in expected_names):
                raise MissingExplainRepair(
                    f"{label}: refusal must cite chase_non_terminating and cycle member {expected_names}, got: {text!r}"
                ) from error
        except pack.CompileError as error:
            raise MissingExplainRepair(
                f"{label}: expected ChaseTerminationError(CompileError), got {type(error).__name__}: {error}"
            ) from error
        else:
            raise MissingExplainRepair(f"{label}: non-terminating cyclic existential require was not refused")

    # Counterexample: an acyclic multi-hop require chain (Rack -> PowerSupply -> FeedPort) is accepted.
    acyclic_dir = _write_pack(tmp_path / "acyclic-chain", ACYCLIC_CHAIN_MODULE)
    try:
        acyclic_model = pack.read(acyclic_dir)
        cert = check_term(acyclic_model)
    except pack.CompileError as error:
        raise MissingExplainRepair(f"acyclic terminating require chain was wrongly refused: {error}") from error
    if not isinstance(cert, dict) or cert.get("terminates") is not True:
        raise MissingExplainRepair(f"expected termination certificate with terminates=True, got: {cert!r}")
    reqs = set(cert.get("requirements", ()))
    if not {"rack_dual_power", "supply_has_port"} <= reqs:
        raise MissingExplainRepair(f"termination certificate missing requirements: {cert!r}")
