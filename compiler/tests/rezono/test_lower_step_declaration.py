"""A step declaration lowers through pack.read to a typed CompiledStep entry in Pack.steps, alongside its
derived match relation in Pack.rules and ir/rules.json, verified against ports/<name>.yaml and pack.yaml
safe_steps bindings (decisions/language-safe-steps.md, sections 2 and 4).

The module form is written by hand from decisions/language-safe-steps.md so this test isolates lowering from
the TypeScript module reader (rezono/test/test_step_declaration.py).
"""

from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, modules, pack, rezono_module
from support import FIXTURE


class MissingStepDeclarationLowering(AssertionError):
    """pack.read did not lower a step declaration and its port bindings as decisions/language-safe-steps.md says."""


def spans_for(body: dict) -> list[dict]:
    return [
        {"at": pointer, "line": str(index + 3), "start": "0", "end": "1"}
        for index, pointer in enumerate(rezono_module.place_pointers(body))
    ]


EFFECT_PORT = {
    "name": "item-apply",
    "version": "0.1.0",
    "kind": "effect",
    "runs_on": "approved_plan",
    "writes": "world",
    "row_source": "journal",
    "runtime": "in_process",
    "effect": {"plan": "item_plan", "apply": "item_install", "status": "item_status"},
    "consumes": ["desired-items"],
    "produces": ["active-items"],
    "freshness": {"cadence": "on_request"},
    "mapping_owner": "ops",
    "losses": [],
    "secrets": [],
    "requires": ["may_execute"],
}

READER_PORT = {
    "name": "item-readback",
    "version": "0.1.0",
    "kind": "in",
    "runs_on": "source",
    "writes": "observation",
    "row_source": "source",
    "runtime": "in_process",
    "consumes": ["readback-query"],
    "produces": ["active-items"],
    "freshness": {"cadence": "live", "max_delay_seconds": 60},
    "mapping_owner": "ops",
    "losses": [],
    "secrets": [],
}

APPROVED_RULE = {
    "rule": "approved_item",
    "columns": [{"name": "item", "type": "Alpha"}],
    "when": {"in": [{"path": ["item"]}, {"kind": "Alpha"}]},
}

ACTIVE_RULE = {
    "rule": "active_beta",
    "columns": [{"name": "target", "type": "Beta"}, {"name": "owner", "type": "Alpha"}],
    "when": {"call": ["Beta.alpha", [{"path": ["target"]}, {"path": ["owner"]}]]},
}

INVENTORY_RULE = {
    "rule": "beta_inventory",
    "columns": [{"name": "scope", "type": "Alpha"}],
    "when": {"in": [{"path": ["scope"]}, {"kind": "Alpha"}]},
}

READBACK_RULE = {
    "rule": "beta_readback",
    "columns": [{"name": "scope", "type": "Alpha"}],
    "when": {"in": [{"path": ["scope"]}, {"kind": "Alpha"}]},
}

STEP_DECL = {
    "step": "install_beta",
    "columns": [{"name": "item", "type": "Alpha"}],
    "when": {"call": ["approved_item", [{"path": ["item"]}]]},
    "forbid": [{
        "pattern": {"call": ["active_beta", [{"wildcard": True}, {"path": ["item"]}]]},
        "within": {"call": ["beta_inventory", [{"path": ["item"]}]]},
    }],
    "effect": {
        "operation": "item_install",
        "changes": [{
            "insert_row": {
                "kind": "Beta",
                "key": {"path": ["item", "id"]},
                "slots": [{"name": "alpha", "value": {"path": ["item"]}}],
            },
        }],
    },
    "confirm": {
        "reader": {"call": ["beta_readback", [{"path": ["item"]}]]},
        "token": {"path": ["item", "title"]},
    },
}


def make_pack(
    tmp_path: Path,
    name: str,
    decls: list[dict],
    *,
    targets: list[dict] | None = None,
    operation: str = "item_install",
    include_ports: bool = True,
) -> Path:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    if include_ports:
        (directory / "ports").mkdir()
        (directory / "ports/item-apply.yaml").write_text(yaml.safe_dump(EFFECT_PORT, sort_keys=False), encoding="utf-8")
        (directory / "ports/item-readback.yaml").write_text(yaml.safe_dump(READER_PORT, sort_keys=False), encoding="utf-8")
    (directory / "rezono").mkdir()
    (directory / "rezono/steps.rezono").write_text("rezono 0\npack minimal\n", encoding="utf-8")
    patched_decls = []
    for decl in decls:
        if "step" in decl:
            decl = json.loads(json.dumps(decl))
            decl["effect"]["operation"] = operation
        patched_decls.append(decl)
    body = {"rezono": "0", "pack": "minimal", "use": [], "decls": patched_decls}
    form = {"format": "rezono.module/4", "spans": spans_for(body), "module": body}
    (directory / "rezono/steps.json").write_text(json.dumps(form), encoding="utf-8")
    meta = yaml.safe_load((directory / "pack.yaml").read_bytes())
    meta["rezono"] = [{"module": "rezono/steps.rezono", "form": "rezono/steps.json", "layer": "facts"}]
    if include_ports:
        meta["safe_steps"] = {
            "readers": [{
                "relation": "beta_readback",
                "port": "item-readback",
                "scope": ["scope"],
                "targets": targets if targets is not None else [
                    {"kind": "beta"},
                    {"kind": "beta", "slot": "alpha"},
                ],
            }],
        }
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return directory


def test_lower_step_declaration(tmp_path):
    # Counter-case 1: an ordinary pack without steps exposes an empty Pack.steps tuple.
    plain_dir = Path(shutil.copytree(FIXTURE, tmp_path / "plain" / "minimal"))
    plain_model = pack.read(plain_dir)
    if not hasattr(plain_model, "steps"):
        raise MissingStepDeclarationLowering("Pack has no steps field")
    assert plain_model.steps == ()

    # Main case: valid step declaration with ports/<name>.yaml and safe_steps.readers bindings.
    decls = [APPROVED_RULE, ACTIVE_RULE, INVENTORY_RULE, READBACK_RULE, STEP_DECL]
    step_dir = make_pack(tmp_path, "valid", decls)
    hash_before = modules.pack_hash(step_dir)
    # ports/<name>.yaml must participate in the pack definition hash (section 4, Pack bindings).
    (step_dir / "ports/item-apply.yaml").write_text(
        yaml.safe_dump(EFFECT_PORT | {"version": "0.1.1"}, sort_keys=False), encoding="utf-8",
    )
    hash_after = modules.pack_hash(step_dir)
    if hash_before == hash_after:
        raise MissingStepDeclarationLowering("ports/<name>.yaml is not included in modules.pack_hash")

    try:
        model = pack.read(step_dir)
    except pack.CompileError as error:
        raise MissingStepDeclarationLowering(str(error)) from error

    assert len(model.steps) == 1
    [step] = model.steps
    assert tuple(step.id) == ("minimal", "steps", "install_beta")
    assert len(step.columns) == 1 and step.columns[0][0] == "item"
    assert len(step.blockers) == 1
    assert step.blockers[0].pattern.relation == "active_beta"
    assert step.blockers[0].coverage.relation == "beta_inventory"
    assert step.operation.port == "item-apply" and step.operation.apply == "item_install"
    assert len(step.changes) == 1 and step.changes[0].op == "insert" and step.changes[0].kind == "beta"
    assert step.confirmation.reader.port == "item-readback"
    assert step.confirmation.reader.call.relation == "beta_readback"
    post_attrs = {(p.attribute.kind, p.attribute.slot) for p in step.confirmation.postconditions}
    assert post_attrs == {("beta", None), ("beta", "alpha")}

    files = emit.compile_pack(model)
    ir = json.loads(files["ir/rules.json"])
    assert any(rel["name"] == step.match_relation for rel in ir["relations"])

    # Counter-case 2: incomplete reader targets (missing promised slot beta.alpha) is refused.
    incomplete_dir = make_pack(tmp_path, "incomplete_targets", decls, targets=[{"kind": "beta"}])
    with pytest.raises(pack.CompileError):
        pack.read(incomplete_dir)

    # Counter-case 3: unresolved effect operation is refused.
    unknown_op_dir = make_pack(tmp_path, "unknown_op", decls, operation="nonexistent_apply")
    with pytest.raises(pack.CompileError):
        pack.read(unknown_op_dir)


def _retract_step(kind: str, slot: str) -> dict:
    return {
        "step": "clear_slot",
        "columns": [{"name": "target", "type": kind}, {"name": "item", "type": "Alpha"}],
        "when": {
            "and": [
                {"in": [{"path": ["target"]}, {"kind": kind}]},
                {"call": ["approved_item", [{"path": ["item"]}]]},
            ],
        },
        "effect": {
            "operation": "item_install",
            "changes": [{
                "retract_slot": {
                    "kind": kind,
                    "slot": slot,
                    "key": {"path": ["target"]},
                },
            }],
        },
        "confirm": {
            "reader": {"call": ["beta_readback", [{"path": ["item"]}]]},
            "token": {"path": ["item", "title"]},
        },
    }


def test_retract_slot_refuses_required_slot(tmp_path):
    # Direct required slot Beta.alpha must be refused with R049.
    required_dir = make_pack(
        tmp_path,
        "retract_required",
        [APPROVED_RULE, READBACK_RULE, _retract_step("Beta", "alpha")],
        targets=[{"kind": "beta", "slot": "alpha"}],
    )
    with pytest.raises(pack.CompileError) as exc_info:
        pack.read(required_dir)
    assert any(d.code == "R049" and "beta.alpha" in d.message for d in exc_info.value.diagnostics)

    # Inherited required slot SubBeta.alpha must also be refused with R049.
    inherited_dir = make_pack(
        tmp_path,
        "retract_inherited_required",
        [APPROVED_RULE, READBACK_RULE, _retract_step("SubBeta", "alpha")],
        targets=[{"kind": "sub_beta", "slot": "alpha"}],
    )
    schema = yaml.safe_load((inherited_dir / "schema/minimal.yaml").read_bytes())
    schema["classes"]["SubBeta"] = {"is_a": "Beta"}
    (inherited_dir / "schema/minimal.yaml").write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
    labels = (inherited_dir / "labels/nl.yaml").read_text(encoding="utf-8")
    (inherited_dir / "labels/nl.yaml").write_text(labels + "\nsub_beta: sub-bèta\n", encoding="utf-8")
    with pytest.raises(pack.CompileError) as exc_info:
        pack.read(inherited_dir)
    assert any(d.code == "R049" and "sub_beta.alpha" in d.message for d in exc_info.value.diagnostics)

    # Counter-case: optional slot Beta.state can still be retracted.
    optional_dir = make_pack(
        tmp_path,
        "retract_optional",
        [APPROVED_RULE, READBACK_RULE, _retract_step("Beta", "state")],
        targets=[{"kind": "beta", "slot": "state"}],
    )
    model = pack.read(optional_dir)
    [step] = model.steps
    assert len(step.changes) == 1
    assert step.changes[0].op == "unset"
    assert step.changes[0].kind == "beta"
    assert step.changes[0].slot == "state"
    assert len(step.confirmation.postconditions) == 1
    post = step.confirmation.postconditions[0]
    assert (post.attribute.kind, post.attribute.slot, post.state) == ("beta", "state", "absent")


def _make_imported_atomic_pack(
    tmp_path: Path,
    name: str,
    decls: list[dict],
    *,
    targets: list[dict],
    boundary: str = "tx-batch",
    evidence: dict[str, str] | None = None,
) -> Path:
    shared = FIXTURE.parent / "shared"
    provider = Path(shutil.copytree(shared, tmp_path / name / "provider"))
    (provider / "ports").mkdir()
    (provider / "ports/item-apply.yaml").write_text(yaml.safe_dump(EFFECT_PORT, sort_keys=False), encoding="utf-8")
    provider_meta = yaml.safe_load((provider / "pack.yaml").read_bytes())
    provider_meta["name"] = "provider"
    provider_meta["safe_steps"] = {
        "atomic_effects": [{
            "operation": "item_install",
            "boundary": boundary,
            "evidence": evidence or {"relation": "atomic_proof", "key": "item-install-failure"},
        }],
    }
    (provider / "pack.yaml").write_text(yaml.safe_dump(provider_meta, sort_keys=False), encoding="utf-8")

    consumer = make_pack(tmp_path, name, decls, targets=targets, include_ports=False)
    (consumer / "ports").mkdir()
    (consumer / "ports/item-readback.yaml").write_text(yaml.safe_dump(READER_PORT, sort_keys=False), encoding="utf-8")
    meta = yaml.safe_load((consumer / "pack.yaml").read_bytes())
    meta["imports"] = [{"name": "provider", "path": "../provider", "sha256": modules.pack_hash(provider)}]
    meta["safe_steps"] = {
        "readers": [{
            "relation": "beta_readback",
            "port": "item-readback",
            "scope": ["scope"],
            "targets": targets,
        }],
    }
    (consumer / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return consumer


def test_imported_atomic_effects_apply_to_steps(tmp_path):
    expected_evidence = {"relation": "atomic_proof", "key": "item-install-failure"}

    # Multi-write step using an imported effect port and its pack's atomic_effects binding.
    multi_step = {
        "step": "update_pair",
        "columns": [{"name": "target", "type": "Beta"}, {"name": "item", "type": "Alpha"}],
        "when": {"call": ["active_beta", [{"path": ["target"]}, {"path": ["item"]}]]},
        "effect": {
            "operation": "item_install",
            "changes": [
                {
                    "set_slot": {
                        "kind": "Alpha",
                        "slot": "size",
                        "key": {"path": ["item"]},
                        "value": {"lit": "1"},
                    },
                },
                {
                    "retract_slot": {
                        "kind": "Beta",
                        "slot": "state",
                        "key": {"path": ["target"]},
                    },
                },
            ],
        },
        "confirm": {
            "reader": {"call": ["beta_readback", [{"path": ["item"]}]]},
            "token": {"path": ["item", "title"]},
        },
    }
    multi_dir = _make_imported_atomic_pack(
        tmp_path,
        "imported_multi",
        [ACTIVE_RULE, READBACK_RULE, multi_step],
        targets=[{"kind": "alpha", "slot": "size"}, {"kind": "beta", "slot": "state"}],
        evidence=expected_evidence,
    )
    multi_model = pack.read(multi_dir)
    [step] = multi_model.steps
    assert len(step.changes) == 2
    assert step.operation.port == "item-apply"
    assert step.operation.apply == "item_install"
    assert step.operation.boundary == "tx-batch"
    assert step.operation.evidence == expected_evidence

    # Single-write step using an imported effect port retains its atomic_effects boundary and evidence.
    single_dir = _make_imported_atomic_pack(
        tmp_path,
        "imported_single",
        [APPROVED_RULE, ACTIVE_RULE, INVENTORY_RULE, READBACK_RULE, STEP_DECL],
        targets=[{"kind": "beta"}, {"kind": "beta", "slot": "alpha"}],
        evidence=expected_evidence,
    )
    single_model = pack.read(single_dir)
    [single_step] = single_model.steps
    assert len(single_step.changes) == 1
    assert single_step.operation.port == "item-apply"
    assert single_step.operation.apply == "item_install"
    assert single_step.operation.boundary == "tx-batch"
    assert single_step.operation.evidence == expected_evidence
