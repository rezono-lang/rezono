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
KNOWLEDGE_TIME_2 = "2026-11-21T01:00:00Z"
ROLES = {"checker": "complete", "viewer": "may_read"}
FACT_SOURCE = (
    'default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
    'position: compiler/tests/rezono/test_explain_repair.py#FACTS}\n'
)
READBACK_SOURCE = (
    'default: {kind: git, name: rezono-lang/rezono, revision: "1111111", '
    'position: compiler/tests/rezono/test_explain_repair.py#READBACK}\n'
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


def _write_rezono_module(folder: Path, stem: str, source: str, layer: str) -> dict:
    module, form = folder / f"{stem}.rezono", folder / f"{stem}.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise MissingExplainRepair(f"write-form.ts failed on {stem}: {result.stderr.strip() or result.stdout.strip()}")
    if json.loads(form.read_bytes()).get("format") != "rezono.module/5":
        raise MissingExplainRepair(f"expected rezono.module/5 for {stem}, got {json.loads(form.read_bytes()).get('format')}")
    return {"module": f"rezono/{stem}.rezono", "form": f"rezono/{stem}.json", "layer": layer}


def _write_pack(
    directory: Path,
    source: str,
    *,
    obs_source: str | None = None,
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
    entries = [_write_rezono_module(folder, "repair_case", source, "facts")]
    if obs_source is not None:
        entries.append(_write_rezono_module(folder, "obs", obs_source, "observation"))
    if facts is not None:
        (directory / "facts").mkdir(exist_ok=True)
        (directory / "facts/case.yaml").write_text(facts, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    if access_rules is not None:
        (directory / "rules").mkdir(exist_ok=True)
        (directory / "rules/access.dl").write_text(access_rules, encoding="utf-8", newline="\n")
    register(directory, *entries)
    return directory


def _read_manifest_state(st: store.FileStore, manifest_id: str, role: str):
    """Read a published manifest, its role snapshots, its role witness set, rules IR, and verified reader."""
    raw = st.get(f"minimal/manifests/{manifest_id}.json")
    if raw is None:
        raise MissingExplainRepair(f"manifest {manifest_id} missing from store")
    manifest = json.loads(raw)
    rules_entry = next(c for c in manifest["compiled"] if c["file"] == "ir/rules.json")
    rules_doc = json.loads(views._get(st, views.key_of(rules_entry["uri"]), rules_entry["sha256"]))
    snap_by_uri = {s["uri"]: s["sha256"] for s in manifest["snapshots"]}

    def read_bytes(uri: str) -> bytes:
        return views._get(st, views.key_of(uri), snap_by_uri[uri])

    rows_by_rel: dict[str, list[list]] = {}
    for snap in manifest["snapshots"]:
        if snap.get("role") == role:
            payload = json.loads(read_bytes(snap["uri"]))
            rows_by_rel[snap["relation"]] = [row["key"] for row in payload]

    witness_entry = next((w for w in manifest.get("witnesses", []) if w.get("role") == role), None)
    if witness_entry is None:
        raise MissingExplainRepair(f"manifest {manifest_id} missing witness set for role {role!r}")
    witness_doc = json.loads(views._get(st, views.key_of(witness_entry["uri"]), witness_entry["sha256"]))
    return raw, manifest, rows_by_rel, witness_doc.get("witnesses", []), rules_doc, read_bytes


def _verify_role_witnesses(manifest: dict, witnesses: list[dict], rules_doc: dict, read_bytes) -> None:
    proof_doc = {
        "format": "rezono.proof/1",
        "manifest_id": manifest["id"],
        "root": None,
        "witnesses": witnesses,
    }
    report = verify_proof(proof_doc, manifest, load_checker_rules(rules_doc), read_bytes)
    if not report["valid"] or report["findings"]:
        raise MissingExplainRepair(f"rezono_checker rejected witnesses for {manifest['id']}: {report}")


def _proof_cites_entity(
    witnesses: list[dict],
    rows_by_rel: dict[str, list[list]],
    root_relation: str,
    root_key: str,
    base_relation: str,
    entity_id: str,
) -> bool:
    """Return True iff the checker-verified witness DAG for (root_relation, root_key) reaches base_relation(entity_id)."""
    by_conclusion = {
        (w["conclusion"]["relation"], w["conclusion"]["key"]): w
        for w in witnesses
        if isinstance(w, dict) and isinstance(w.get("conclusion"), dict)
    }
    stack = [(root_relation, root_key)]
    seen: set[tuple[str, str]] = set()
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        witness = by_conclusion.get(node)
        if witness is None:
            continue
        for premise in witness.get("premises", ()):
            if premise.get("polarity") != "positive":
                continue
            row = premise.get("row") or {}
            rel, key = row.get("relation"), row.get("key")
            if not isinstance(rel, str) or not isinstance(key, str):
                continue
            if rel == base_relation and entity_id in json.loads(key):
                return True
            stack.append((rel, key))
        for agg in witness.get("aggregates", ()):
            if not isinstance(agg, dict) or agg.get("count", 0) <= 0:
                continue
            rel, group_key = agg.get("relation"), agg.get("group_key")
            if not isinstance(rel, str) or not isinstance(group_key, str):
                continue
            prefix = json.loads(group_key)
            for row_key in rows_by_rel.get(rel, ()):
                if row_key[: len(prefix)] == prefix:
                    if rel == base_relation and entity_id in row_key:
                        return True
                    stack.append((rel, json.dumps(row_key, separators=(",", ":"))))
    return False


def _rows_for_subject(rows_by_rel: dict[str, list[list]], relation: str, subject: str) -> list[list]:
    return [row for row in rows_by_rel.get(relation, ()) if row and row[0] == subject]


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
    expected_messages = (
        "explain.repair",
        "explain.repair.question",
        "explain.not_computed.chase_non_terminating",
        "explain.not_computed.incomplete_evidence",
        "explain.not_computed.invalid_input",
        "explain.not_computed.not_additive",
        "explain.not_computed.observation_immutable",
    )
    for lang in ("en", "nl"):
        text = (STD_EXPLAIN / "messages" / f"{lang}.mf2").read_text(encoding="utf-8")
        for key in expected_messages:
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

require physical_power_supply_a_present(r: Rack)
  exists obs: PowerSupplyReadback where obs.rack = r and obs.bus = bus_a
"""

POWER_OBS_MODULE = """\
rezono 1
pack minimal

kind PowerSupplyReadback world open
  rack: Rack
  bus: Bus
  serial: Text
"""

POWER_REPAIR_FACTS = """\
rack:
  - {id: rack-b-only}
  - {id: rack-both}
power_supply:
  - {id: ps-1, rack: rack-b-only, bus: bus_b, serial: "SN-B1"}
  - {id: ps-2a, rack: rack-both, bus: bus_a, serial: "SN-A2"}
  - {id: ps-2b, rack: rack-both, bus: bus_b, serial: "SN-B2"}
power_supply_readback:
  - {id: obs-1, rack: rack-b-only, bus: bus_b, serial: "SN-B1"}
  - {id: obs-2a, rack: rack-both, bus: bus_a, serial: "SN-A2"}
  - {id: obs-2b, rack: rack-both, bus: bus_b, serial: "SN-B2"}
"""

POWER_READBACK_A_FACTS = """\
power_supply_readback:
  - {id: obs-a1, rack: rack-b-only, bus: bus_a, serial: "SN-A1-MEASURED"}
"""

POWER_ACCESS_RULES = """\
.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "rack", r) :- rack(r).
may_read("viewer", "power_supply", ps) :- power_supply(ps).
may_read("viewer", "power_supply_readback", obs) :- power_supply_readback(obs).
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingExplainRepair,
    reason=(
        "extra: decisions/explain-repair.md: Derive minimal additive chase repair for an unmet "
        "require declaration (rack with only power supply B proposes power supply A with unknown "
        "placeholder slot), replay via suppose, verify both the suppose scenario (with proposed A "
        "as witness) and unchanged original inventory, prove physical presence of A only after an "
        "independent readback observation in a new publication, and return no repair when both "
        "supplies already exist. "
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
        obs_source=POWER_OBS_MODULE,
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

    # Capture original inventory (m-1) state for rack-b-only BEFORE suppose.
    base_raw_before, base_m_before, base_rows_before, _, _, _ = _read_manifest_state(st, "m-1", "viewer")
    base_dual_before = _rows_for_subject(base_rows_before, "rack_dual_power", "rack-b-only")
    base_viol_before = _rows_for_subject(base_rows_before, "rack_dual_power_violation", "rack-b-only")
    base_supplies_before = sorted(base_rows_before.get("power_supply", ()))
    base_physical_a_before = _rows_for_subject(base_rows_before, "physical_power_supply_a_present", "rack-b-only")
    if (
        base_dual_before != [["rack-b-only", "known", "", "false"]]
        or base_viol_before != [["rack-b-only", "0", "power_supply", "at_least:1", "0"]]
        or base_physical_a_before != [["rack-b-only", "unknown", "open_world", ""]]
    ):
        raise MissingExplainRepair(
            f"unexpected pre-suppose m-1 state for rack-b-only: dual={base_dual_before} "
            f"viol={base_viol_before} physical_a={base_physical_a_before}"
        )

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

    # Query BOTH the suppose scenario AND the original inventory (m-1) for rack-b-only after suppose.
    sup_mid = sup["manifest"]
    _, sup_manifest, sup_rows, sup_witnesses, sup_rules_doc, sup_read_bytes = _read_manifest_state(st, sup_mid, "viewer")

    report = verify_proof(witness, sup_manifest, load_checker_rules(sup_rules_doc), sup_read_bytes)
    if not report["valid"] or report["findings"]:
        raise MissingExplainRepair(f"rezono_checker rejected repair witness: {report}")
    if not any(
        w.get("conclusion") == {"relation": "rack_dual_power", "key": '["rack-b-only","known","","true"]'}
        for w in witness.get("witnesses", [])
    ):
        raise MissingExplainRepair(f"witness does not prove rack_dual_power(rack-b-only) = known true: {witness}")

    _verify_role_witnesses(sup_manifest, sup_witnesses, sup_rules_doc, sup_read_bytes)
    if (
        _rows_for_subject(sup_rows, "rack_dual_power", "rack-b-only") != [["rack-b-only", "known", "", "true"]]
        or _rows_for_subject(sup_rows, "rack_dual_power_violation", "rack-b-only") != []
    ):
        raise MissingExplainRepair(f"suppose scenario did not satisfy rack_dual_power for rack-b-only: {sup_rows}")
    if not _proof_cites_entity(
        sup_witnesses,
        sup_rows,
        "rack_dual_power",
        '["rack-b-only","known","","true"]',
        "power_supply",
        fresh_key,
    ):
        raise MissingExplainRepair(
            f"suppose scenario proof for rack_dual_power(rack-b-only) must cite proposed power supply {fresh_key!r}"
        )
    if _rows_for_subject(sup_rows, "physical_power_supply_a_present", "rack-b-only") != [
        ["rack-b-only", "unknown", "open_world", ""]
    ]:
        raise MissingExplainRepair(
            "speculative suppose proposal must NOT prove physical presence of power supply A"
        )

    # Original inventory (m-1) must return the exact same answer as before suppose (zero side-effect mutation).
    base_raw_after, _, base_rows_after, _, _, _ = _read_manifest_state(st, "m-1", "viewer")
    if base_raw_after != base_raw_before:
        raise MissingExplainRepair("suppose mutated the original m-1 manifest in the store")
    if (
        _rows_for_subject(base_rows_after, "rack_dual_power", "rack-b-only") != base_dual_before
        or _rows_for_subject(base_rows_after, "rack_dual_power_violation", "rack-b-only") != base_viol_before
        or sorted(base_rows_after.get("power_supply", ())) != base_supplies_before
        or _rows_for_subject(base_rows_after, "physical_power_supply_a_present", "rack-b-only") != base_physical_a_before
        or [fresh_key] in base_rows_after.get("power_supply", ())
    ):
        raise MissingExplainRepair(
            f"original inventory m-1 changed after suppose: dual={_rows_for_subject(base_rows_after, 'rack_dual_power', 'rack-b-only')} "
            f"viol={_rows_for_subject(base_rows_after, 'rack_dual_power_violation', 'rack-b-only')} "
            f"supplies={base_rows_after.get('power_supply')}"
        )

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

    # Feed an independent readback (observation) of power supply A on rack-b-only into a new publication (m-2).
    # ONLY in m-2 can physical presence of A be proven, with the independent readback as witness.
    (pack_dir / "facts" / "readback.yaml").write_text(POWER_READBACK_A_FACTS, encoding="utf-8", newline="\n")
    (pack_dir / "facts" / "readback.sources.yaml").write_text(READBACK_SOURCE, encoding="utf-8", newline="\n")
    try:
        epoch2 = publisher_batch.epoch(
            pack_dir,
            epoch=2,
            knowledge_time=KNOWLEDGE_TIME_2,
            sources=[("facts", "1"), ("readback", "2")],
        )
        m2 = publish.publish(epoch2, st, ROLES)
    except Exception as error:
        raise MissingExplainRepair(f"failed to publish readback epoch m-2: {error}") from error
    if m2["id"] != "m-2":
        raise MissingExplainRepair(f"expected readback manifest m-2, got {m2['id']}")

    _, m2_manifest, m2_rows, m2_witnesses, m2_rules_doc, m2_read_bytes = _read_manifest_state(st, "m-2", "viewer")
    _verify_role_witnesses(m2_manifest, m2_witnesses, m2_rules_doc, m2_read_bytes)
    if _rows_for_subject(m2_rows, "physical_power_supply_a_present", "rack-b-only") != [
        ["rack-b-only", "known", "", "true"]
    ]:
        raise MissingExplainRepair(
            f"m-2 with independent readback must prove physical_power_supply_a_present(rack-b-only) = known true: "
            f"{_rows_for_subject(m2_rows, 'physical_power_supply_a_present', 'rack-b-only')}"
        )
    if not _proof_cites_entity(
        m2_witnesses,
        m2_rows,
        "physical_power_supply_a_present",
        '["rack-b-only","known","","true"]',
        "power_supply_readback",
        "obs-a1",
    ):
        raise MissingExplainRepair("m-2 proof of physical presence of power supply A must cite readback 'obs-a1'")
    if _proof_cites_entity(
        m2_witnesses,
        m2_rows,
        "physical_power_supply_a_present",
        '["rack-b-only","known","","true"]',
        "power_supply",
        fresh_key,
    ):
        raise MissingExplainRepair("physical presence proof in m-2 must never cite the speculative proposal key")


MINIMAL_ANY_THEN_B_MODULE = """\
rezono 1
pack minimal

enum Bus = bus_a | bus_b

kind Rack
kind PowerSupply
  rack: Rack
  bus: Bus
  serial: Text

require rack_has_any_power(r: Rack)
  exists at least 1 ps_any: PowerSupply where ps_any.rack = r

require rack_has_bus_b_power(r: Rack)
  exists at least 1 ps_b: PowerSupply where ps_b.rack = r and ps_b.bus = bus_b

require rack_power_minimum(r: Rack)
  exists at least 1 ps_any: PowerSupply where ps_any.rack = r
  exists at least 1 ps_b: PowerSupply where ps_b.rack = r and ps_b.bus = bus_b
  means "{$r} must have at least one power supply and at least one B power supply." @ policy#power-min

require physical_power_supply_b_present(r: Rack)
  exists obs: PowerSupplyReadback where obs.rack = r and obs.bus = bus_b
"""

MINIMAL_B_THEN_ANY_MODULE = """\
rezono 1
pack minimal

enum Bus = bus_a | bus_b

kind Rack
kind PowerSupply
  rack: Rack
  bus: Bus
  serial: Text

require rack_has_any_power(r: Rack)
  exists at least 1 ps_any: PowerSupply where ps_any.rack = r

require rack_has_bus_b_power(r: Rack)
  exists at least 1 ps_b: PowerSupply where ps_b.rack = r and ps_b.bus = bus_b

require rack_power_minimum(r: Rack)
  exists at least 1 ps_b: PowerSupply where ps_b.rack = r and ps_b.bus = bus_b
  exists at least 1 ps_any: PowerSupply where ps_any.rack = r
  means "{$r} must have at least one B power supply and at least one power supply." @ policy#power-min

require physical_power_supply_b_present(r: Rack)
  exists obs: PowerSupplyReadback where obs.rack = r and obs.bus = bus_b
"""

EMPTY_RACK_FACTS = """\
rack:
  - {id: rack-empty}
"""

EMPTY_RACK_READBACK_B_FACTS = """\
power_supply_readback:
  - {id: obs-b1, rack: rack-empty, bus: bus_b, serial: "SN-B1-MEASURED"}
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingExplainRepair,
    reason=(
        "extra: decisions/explain-repair.md: For an empty desired rack requiring both at least one "
        "power supply and at least one B power supply, in BOTH clause orders ([any, bus_b] and "
        "[bus_b, any]), Layer-1 chase proposes ONE single B power supply (inclusion- and "
        "cardinality-minimal) that witnesses both requirements via suppose and rezono_checker, "
        "while physical inventory evidence still comes solely from an observation. "
        "Waits for compiler/tests/rezono/test_language_requirements.py--test_requirement_violation_witness_cites_trigger_and_missing_pattern."
    ),
)
def test_repair_chase_single_row_minimality_across_clause_orders(tmp_path):
    _check_std_explain_declares_repair()
    repair_mod = _import_required("rezono_publisher.repair")
    if not hasattr(repair_mod, "repair"):
        raise MissingExplainRepair("rezono_publisher.repair.repair is not defined")

    for order_label, module_source in (
        ("any-then-b", MINIMAL_ANY_THEN_B_MODULE),
        ("b-then-any", MINIMAL_B_THEN_ANY_MODULE),
    ):
        case_root = tmp_path / order_label
        pack_dir = _write_pack(
            case_root / "pack",
            module_source,
            obs_source=POWER_OBS_MODULE,
            facts=EMPTY_RACK_FACTS,
            access_rules=POWER_ACCESS_RULES,
            import_std_explain=True,
        )
        st = store.FileStore(case_root / "store")
        try:
            epoch = publisher_batch.epoch(
                pack_dir,
                epoch=1,
                knowledge_time=KNOWLEDGE_TIME,
                sources=[("facts", "1")],
            )
            base_manifest = publish.publish(epoch, st, ROLES)
        except Exception as error:
            raise MissingExplainRepair(f"{order_label}: failed to publish base pack: {error}") from error
        if base_manifest["id"] != "m-1":
            raise MissingExplainRepair(f"{order_label}: expected m-1, got {base_manifest['id']}")

        answer = repair_mod.repair(pack_dir, st, "m-1", "viewer", "rack_power_minimum", ["rack-empty"])
        if errors := _validate("explain.yaml", answer, "Answer"):
            raise MissingExplainRepair(f"{order_label}: invalid Answer: {errors[:5]}")
        rep = answer.get("repair")
        if (
            answer.get("question") != "repair"
            or answer.get("computed") is not True
            or answer.get("not_computed") is not None
            or not isinstance(rep, dict)
            or rep.get("needed") is not True
            or rep.get("cut") is not False
        ):
            raise MissingExplainRepair(f"{order_label}: unexpected repair envelope: {answer}")
        proposals = rep.get("proposals", [])
        if len(proposals) != 1:
            raise MissingExplainRepair(f"{order_label}: expected 1 minimal proposal, got {len(proposals)}")

        prop = proposals[0]
        delta = prop.get("delta")
        if not isinstance(delta, dict) or (errors := _validate("delta.yaml", delta, "Delta")):
            raise MissingExplainRepair(f"{order_label}: invalid proposal delta: {errors if isinstance(delta, dict) else delta}")
        changes = delta.get("changes", [])
        additions = prop.get("additions", [])
        if len(changes) != 1 or len(additions) != 1:
            raise MissingExplainRepair(
                f"{order_label}: cardinality/inclusion minimality violated — expected ONE single B power supply, "
                f"got {len(changes)} changes and {len(additions)} additions: changes={changes}"
            )

        ch = changes[0]
        fresh_key = ch.get("key")
        values = ch.get("values") or {}
        if (
            ch.get("op") != "insert"
            or ch.get("kind") != "power_supply"
            or not isinstance(fresh_key, str)
            or not fresh_key
            or values.get("rack") != "rack-empty"
            or values.get("bus") != "bus_b"
            or "serial" in values
        ):
            raise MissingExplainRepair(f"{order_label}: expected single bus_b PowerSupply without fabricated serial: {ch}")

        add = additions[0]
        slots = add.get("slots") or {}
        if (
            add.get("kind") != "power_supply"
            or add.get("key") != fresh_key
            or add.get("key_unknown") is not True
            or slots.get("rack") != {"state": "known", "value": "rack-empty"}
            or slots.get("bus") != {"state": "known", "value": "bus_b"}
            or slots.get("serial") != {"state": "unknown", "reason": "to_be_filled"}
        ):
            raise MissingExplainRepair(f"{order_label}: unexpected RepairAddition: {add}")

        sup = prop.get("supposition")
        if (
            not isinstance(sup, dict)
            or sup.get("format") != "rezono.supposition/1"
            or sup.get("base_manifest") != "m-1"
            or not str(sup.get("manifest", "")).startswith("p-local-")
            or sup.get("withheld") is not None
        ):
            raise MissingExplainRepair(f"{order_label}: invalid supposition: {sup}")

        diff_rows = sup.get("rows", [])
        for clause_idx in ("0", "1"):
            if not any(
                r.get("relation") == "rack_power_minimum_violation"
                and r.get("weight") == -1
                and r.get("key") == ["rack-empty", clause_idx, "power_supply", "at_least:1", "0"]
                for r in diff_rows
            ):
                raise MissingExplainRepair(
                    f"{order_label}: suppose diff did not clear clause {clause_idx} violation: {diff_rows}"
                )

        if prop.get("verified") is not True or not isinstance(prop.get("witness"), dict):
            raise MissingExplainRepair(f"{order_label}: proposal must be verified with a proof witness: {prop}")

        sup_mid = sup["manifest"]
        _, sup_manifest, sup_rows, sup_witnesses, sup_rules_doc, sup_read_bytes = _read_manifest_state(
            st, sup_mid, "viewer"
        )
        report = verify_proof(prop["witness"], sup_manifest, load_checker_rules(sup_rules_doc), sup_read_bytes)
        if not report["valid"] or report["findings"]:
            raise MissingExplainRepair(f"{order_label}: rezono_checker rejected proposal witness: {report}")
        _verify_role_witnesses(sup_manifest, sup_witnesses, sup_rules_doc, sup_read_bytes)

        if sup_rows.get("power_supply") != [[fresh_key]]:
            raise MissingExplainRepair(
                f"{order_label}: supposed manifest must contain exactly ONE power_supply [{fresh_key!r}], "
                f"got {sup_rows.get('power_supply')}"
            )
        for req_name in ("rack_power_minimum", "rack_has_any_power", "rack_has_bus_b_power"):
            if _rows_for_subject(sup_rows, req_name, "rack-empty") != [["rack-empty", "known", "", "true"]]:
                raise MissingExplainRepair(f"{order_label}: {req_name}(rack-empty) did not become known true")
            if not _proof_cites_entity(
                sup_witnesses,
                sup_rows,
                req_name,
                '["rack-empty","known","","true"]',
                "power_supply",
                fresh_key,
            ):
                raise MissingExplainRepair(
                    f"{order_label}: single proposed row {fresh_key!r} must witness {req_name}(rack-empty)"
                )

        # Physical inventory evidence must still come solely from an observation (never from the proposal).
        if (
            sup_rows.get("power_supply_readback", []) != []
            or _rows_for_subject(sup_rows, "physical_power_supply_b_present", "rack-empty")
            != [["rack-empty", "unknown", "open_world", ""]]
        ):
            raise MissingExplainRepair(
                f"{order_label}: speculative repair proposal must not establish physical inventory evidence"
            )

        # Original inventory (m-1) remains unchanged.
        _, _, base_rows_after, _, _, _ = _read_manifest_state(st, "m-1", "viewer")
        if (
            base_rows_after.get("power_supply", []) != []
            or _rows_for_subject(base_rows_after, "rack_power_minimum", "rack-empty")
            != [["rack-empty", "known", "", "false"]]
        ):
            raise MissingExplainRepair(f"{order_label}: original m-1 inventory changed after suppose")

        # Only an independent observation readback published into m-2 proves physical presence of power supply B.
        (pack_dir / "facts" / "readback.yaml").write_text(EMPTY_RACK_READBACK_B_FACTS, encoding="utf-8", newline="\n")
        (pack_dir / "facts" / "readback.sources.yaml").write_text(READBACK_SOURCE, encoding="utf-8", newline="\n")
        try:
            epoch2 = publisher_batch.epoch(
                pack_dir,
                epoch=2,
                knowledge_time=KNOWLEDGE_TIME_2,
                sources=[("facts", "1"), ("readback", "2")],
            )
            m2 = publish.publish(epoch2, st, ROLES)
        except Exception as error:
            raise MissingExplainRepair(f"{order_label}: failed to publish readback m-2: {error}") from error
        if m2["id"] != "m-2":
            raise MissingExplainRepair(f"{order_label}: expected m-2, got {m2['id']}")
        _, m2_manifest, m2_rows, m2_witnesses, m2_rules_doc, m2_read_bytes = _read_manifest_state(st, "m-2", "viewer")
        _verify_role_witnesses(m2_manifest, m2_witnesses, m2_rules_doc, m2_read_bytes)
        if _rows_for_subject(m2_rows, "physical_power_supply_b_present", "rack-empty") != [
            ["rack-empty", "known", "", "true"]
        ]:
            raise MissingExplainRepair(f"{order_label}: m-2 readback must prove physical_power_supply_b_present")
        if not _proof_cites_entity(
            m2_witnesses,
            m2_rows,
            "physical_power_supply_b_present",
            '["rack-empty","known","","true"]',
            "power_supply_readback",
            "obs-b1",
        ):
            raise MissingExplainRepair(f"{order_label}: physical presence proof in m-2 must cite readback 'obs-b1'")


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
        "chase does not terminate (each Node requires a distinct backup Node, citing node_has_backup) "
        "with chase_non_terminating, while accepting an acyclic terminating require declaration. "
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
        ("self-cycle", CYCLIC_SELF_MODULE, ("node_has_backup",)),
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
