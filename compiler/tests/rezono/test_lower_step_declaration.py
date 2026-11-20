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


@pytest.mark.xfail(
    strict=True,
    raises=MissingStepDeclarationLowering,
    reason="extra: decisions/language-safe-steps.md: Include ports/<name>.yaml in compiler/rezono_compiler/modules.py "
           "DEFINITION (note: adding ports/ to DEFINITION changes pack import pins and the standard pack hash table "
           "in compiler/rezono_compiler/standard_packs.py for packs carrying ports/), load ports via rezono_ports.load "
           "and safe_steps bindings in pack.yaml, admit step declarations in rezono.module/4, and expose Pack.steps "
           "(empty tuple when unused) with CompiledStep (id, match_relation emitted in Pack.rules/ir/rules.json, "
           "typed columns, blockers, operation, changes, confirmation with derived identity and slot postconditions). "
           "Refuse unresolved operations and incomplete reader targets with CompileError. "
           "Blocked for a worker PR: scripts/test_red_guard.py requires scripts/red_guard.py DEFINITION to match "
           "compiler/rezono_compiler/modules.py DEFINITION, while scripts/red_guard.py is a POLICY file that cannot "
           "be changed without planner or alongside a lifted xfail mark; a planner must add ports/*.yaml to DEFINITION "
           "in both files first (rezono.module/4 admission already landed in #1089, and no packs/std-* pack currently "
           "carries ports/ files so standard_packs.py hashes are unchanged).",
)
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
