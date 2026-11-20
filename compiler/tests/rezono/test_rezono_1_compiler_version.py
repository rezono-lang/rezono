"""Compiler version switch and contracts for rezono 1: rezono.module/5, side-by-side rezono 0 and rezono 1 packs,
pack-wide version enforcement (R027), missing rezono line refusal (R028), table priority refusal in rezono 1 (R028),
and pack language version in contracts/bundle.yaml / bundle/schema-bundle.json
(decisions/language-rezono-1.md, sections 1, 3.2, 5.8 and 8)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader
import pytest
import yaml

from rezono_compiler import emit, pack, rezono_module
from support import FIXTURE

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"


class MissingRezono1CompilerVersion(AssertionError):
    """The compiler or contracts did not admit rezono.module/5, enforce pack version rules, or record language version."""


def _validator(schema_name: str) -> Validator:
    definition = yaml_loader.load(str(CONTRACTS / schema_name), target_class=SchemaDefinition)
    return Validator(definition, validation_plugins=[JsonschemaValidationPlugin(closed=True)])


def _validate(schema_name: str, instance: dict, target_class: str) -> list[str]:
    report = _validator(schema_name).validate(instance, target_class)
    return [item.message for item in report.results]


def _write_metadata(directory: Path, **changes) -> None:
    path = directory / "pack.yaml"
    metadata = yaml.safe_load(path.read_text(encoding="utf-8"))
    metadata.update(changes)
    path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8", newline="\n")


def _add_reason_messages(directory: Path) -> None:
    mf2 = directory / "messages" / "nl.mf2"
    text = mf2.read_text(encoding="utf-8")
    mf2.write_text(
        text.rstrip("\n") + "\nreason.no_row_applies = No row applies\nreason.no_value = No value\n",
        encoding="utf-8", newline="\n",
    )


def _form(fmt: str, *, rezono: str | None, pack_name: str = "minimal", decls: list[dict]) -> dict:
    module: dict = {"pack": pack_name, "use": [], "decls": decls}
    if rezono is not None:
        module["rezono"] = rezono
    spans = [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(module)]
    return {"format": fmt, "module": module, "spans": spans}


def _write_form_module(directory: Path, stem: str, form: dict) -> dict:
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    mod_path = folder / f"{stem}.rezono"
    form_path = folder / f"{stem}.json"
    module = form["module"]
    header = ([f"rezono {module['rezono']}"] if "rezono" in module else []) + [f"pack {module['pack']}"]
    mod_path.write_text("\n".join(header) + "\n", encoding="utf-8", newline="\n")
    form_path.write_text(json.dumps(form, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return {"module": f"rezono/{mod_path.name}", "form": f"rezono/{form_path.name}", "layer": "facts"}


def _pack_language_version(bundle: dict) -> str | None:
    info = bundle.get("pack", {})
    return info.get("language_version", info.get("rezono"))


def _error_text(exc: pack.CompileError) -> str:
    parts = [str(exc)]
    for diag in getattr(exc, "diagnostics", ()):
        parts.append(f"{getattr(diag, 'code', '')} {getattr(diag, 'message', '')} {getattr(diag, 'hint', '')}")
    return " ".join(parts)


LEVEL_ENUM = {"enum": "Level", "values": ["low", "high"]}
ITEM_KIND = {
    "kind": "Item",
    "world": "closed",
    "slots": [{"slot": "grade", "type": "Level"}],
    "derived": [],
}
PRIORITY_EXTEND = {
    "extend": "Item",
    "derived": [{
        "derived": "tier",
        "type": "Level",
        "table": {
            "table": "priority",
            "inputs": [{"path": ["grade"]}],
            "output": "tier",
            "rows": [
                {"tests": [[{"lit": "high"}]], "value": {"lit": "high"}},
                {"tests": ["-"], "value": {"lit": "low"}},
            ],
        },
    }],
}
PANEL_KIND = {
    "kind": "Panel",
    "world": "closed",
    "slots": [{"slot": "active", "type": "Bool"}],
    "derived": [],
}
TAG_KIND = {
    "kind": "Tag",
    "world": "closed",
    "slots": [{"slot": "label", "type": "Text"}],
    "derived": [],
}
NOTE_KIND = {
    "kind": "Note",
    "world": "closed",
    "slots": [{"slot": "body", "type": "Text"}],
    "derived": [],
}


def test_compiler_admits_rezono_module_5_and_enforces_pack_version(tmp_path):
    # Counter-case: a rezono 0 module with `table priority` still validates against rezono.module/1 and compiles.
    v0_form = _form("rezono.module/1", rezono="0", decls=[LEVEL_ENUM, ITEM_KIND, PRIORITY_EXTEND])
    assert _validate("rezono-module.yaml", v0_form, "ModuleForm") == []
    v0_dir = Path(shutil.copytree(FIXTURE, tmp_path / "pack_v0"))
    _add_reason_messages(v0_dir)
    v0_entry = _write_form_module(v0_dir, "items", v0_form)
    _write_metadata(v0_dir, rezono=[v0_entry])
    v0_files = emit.compile_pack(pack.read(v0_dir))
    v0_bundle = json.loads(v0_files["bundle/schema-bundle.json"])
    assert _validate("bundle.yaml", v0_bundle, "Bundle") == []

    problems: list[str] = []

    # 1. contracts/bundle.yaml + bundle/schema-bundle.json must record pack language version ("0" for rezono 0).
    if _pack_language_version(v0_bundle) != "0":
        problems.append(f"rezono 0 bundle.pack did not record language version '0': {v0_bundle['pack']!r}")

    # 2. contracts/rezono-module.yaml must admit rezono.module/5 (with rezono == "1") and reject invalid v5 forms.
    valid_v5 = _form("rezono.module/5", rezono="1", decls=[PANEL_KIND])
    v5_errors = _validate("rezono-module.yaml", valid_v5, "ModuleForm")
    if v5_errors:
        problems.append(f"contracts/rezono-module.yaml rejected valid rezono.module/5: {v5_errors}")
    else:
        if not _validate("rezono-module.yaml", _form("rezono.module/5", rezono=None, decls=[PANEL_KIND]), "ModuleForm"):
            problems.append("contracts/rezono-module.yaml admitted rezono.module/5 without module.rezono")
        if not _validate("rezono-module.yaml", _form("rezono.module/5", rezono="0", decls=[PANEL_KIND]), "ModuleForm"):
            problems.append("contracts/rezono-module.yaml admitted rezono.module/5 with module.rezono == '0'")
        pipe_form = _form("rezono.module/5", rezono="1",
                          decls=[{"rules": "legacy", "lines": [".decl listed(x: symbol)"]}])
        if not _validate("rezono-module.yaml", pipe_form, "ModuleForm"):
            problems.append("contracts/rezono-module.yaml admitted rezono 0 `rules` pipe block inside rezono.module/5")
        prio_v5 = _form("rezono.module/5", rezono="1", decls=[LEVEL_ENUM, ITEM_KIND, PRIORITY_EXTEND])
        if not _validate("rezono-module.yaml", prio_v5, "ModuleForm"):
            problems.append("contracts/rezono-module.yaml admitted `table priority` inside rezono.module/5")

    # 3. Compiler accepts a rezono 1 pack side by side with rezono 0 and records language version "1" in bundle.
    v1_dir = Path(shutil.copytree(FIXTURE, tmp_path / "pack_v1"))
    v1_entry = _write_form_module(v1_dir, "panels", valid_v5)
    _write_metadata(v1_dir, rezono=[v1_entry])
    try:
        v1_files = emit.compile_pack(pack.read(v1_dir))
    except pack.CompileError as exc:
        problems.append(f"compiler rejected valid rezono 1 pack: {exc}")
    else:
        v1_bundle = json.loads(v1_files["bundle/schema-bundle.json"])
        bundle_errs = _validate("bundle.yaml", v1_bundle, "Bundle")
        if bundle_errs:
            problems.append(f"rezono 1 bundle failed contracts/bundle.yaml validation: {bundle_errs}")
        if _pack_language_version(v1_bundle) != "1":
            problems.append(f"rezono 1 bundle.pack did not record language version '1': {v1_bundle['pack']!r}")
        if "panel" not in {k["id"] for k in v1_bundle["kinds"]}:
            problems.append("rezono 1 pack did not lower kind Panel into bundle/schema-bundle.json")

    # 4. Pack-wide version consistency (R027): mixing rezono 0 and rezono 1 modules in one pack is refused.
    mixed_dir = Path(shutil.copytree(FIXTURE, tmp_path / "pack_mixed"))
    mixed_v0 = _write_form_module(mixed_dir, "mod_a", _form("rezono.module/1", rezono="0", decls=[TAG_KIND]))
    mixed_v1 = _write_form_module(mixed_dir, "mod_b", valid_v5)
    _write_metadata(mixed_dir, rezono=[mixed_v0, mixed_v1])
    try:
        pack.read(mixed_dir)
    except pack.CompileError as exc:
        if "R027" not in _error_text(exc):
            problems.append(f"mixed rezono 0 / rezono 1 pack failed without R027: {_error_text(exc)}")
    else:
        problems.append("compiler accepted a pack mixing rezono 0 and rezono 1 modules (expected R027)")

    # 5. Missing rezono version line in a rezono 1 pack is refused with R028.
    missing_dir = Path(shutil.copytree(FIXTURE, tmp_path / "pack_missing_version"))
    m1 = _write_form_module(missing_dir, "mod_a", valid_v5)
    m2 = _write_form_module(missing_dir, "mod_b", _form("rezono.module/1", rezono=None, decls=[NOTE_KIND]))
    _write_metadata(missing_dir, rezono=[m1, m2])
    try:
        pack.read(missing_dir)
    except pack.CompileError as exc:
        if "R028" not in _error_text(exc):
            problems.append(f"missing rezono version line in rezono 1 pack failed without R028: {_error_text(exc)}")
    else:
        problems.append("compiler accepted a module missing `rezono` version line in a rezono 1 pack (expected R028)")

    # 6. `table priority` in a rezono 1 module is refused with R028 and hints `table first`.
    prio_dir = Path(shutil.copytree(FIXTURE, tmp_path / "pack_v1_priority"))
    _add_reason_messages(prio_dir)
    prio_entry = _write_form_module(prio_dir, "items", _form("rezono.module/5", rezono="1",
                                                             decls=[LEVEL_ENUM, ITEM_KIND, PRIORITY_EXTEND]))
    _write_metadata(prio_dir, rezono=[prio_entry])
    try:
        pack.read(prio_dir)
    except pack.CompileError as exc:
        text = _error_text(exc)
        if "R028" not in text or "table first" not in text:
            problems.append(f"table priority in rezono 1 failed without R028 + `table first` hint: {text}")
    else:
        problems.append("compiler accepted `table priority` in a rezono 1 module (expected R028 with `table first` hint)")

    if problems:
        raise MissingRezono1CompilerVersion("\n".join(problems))
