"""The subsidy examples copied for a calculation lowering test, and a module form written beside them.

A test replaces (part of) a calc/*.yaml file with a hand-written module form and compares the bound program
with the one the existing file gives (decisions/language-calculations.md, Lowering to the calculation model).
The module text holds only its header, so the form is lowered as written, without the reader."""

from pathlib import Path
import json
import shutil

import yaml

from rezono_compiler import emit, pack, rezono_module


ROOT = Path(__file__).resolve().parents[3]
SUBSIDY = "examples/subsidy"


def imported_example(example: str) -> str:
    """The one example pack that `example` imports, as a path from the repository root."""
    meta = yaml.safe_load((ROOT / example / "pack.yaml").read_bytes())
    [path] = [(ROOT / example / entry["path"]).resolve() for entry in meta["imports"]
              if (ROOT / example / entry["path"]).resolve().parent == (ROOT / "examples").resolve()]
    return path.relative_to(ROOT.resolve()).as_posix()


# The scheme the subsidy example imports: its definition, with the award calculation.
SCHEME = imported_example(SUBSIDY)


def strip_award(scheme_dir: Path) -> None:
    """Remove the scheme's award calculation whether it lives in YAML or in a rezono/ module."""
    legacy = scheme_dir / "calc" / "award.yaml"
    if legacy.exists():
        legacy.unlink()
    for suffix in (".rezono", ".json"):
        candidate = scheme_dir / "rezono" / f"award{suffix}"
        if candidate.exists():
            candidate.unlink()
    meta_path = scheme_dir / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    entries = [e for e in meta.get("rezono") or [] if e.get("module") != "rezono/award.rezono"]
    if entries:
        meta["rezono"] = entries
    else:
        meta.pop("rezono", None)
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def examples(root: Path) -> Path:
    """The two subsidy examples and the standard packs, at their own relative places under `root`."""
    shutil.copytree(ROOT / "packs", root / "packs")
    for example in (SCHEME, SUBSIDY):
        shutil.copytree(ROOT / example, root / example)
    return root


def calc_ir(pack_dir: Path) -> dict:
    """The bound calculation program, ir/calc.json, and the other calculation files of the publication."""
    files = emit.compile_pack(pack.read(pack_dir))
    return {name: (json.loads(text) if name.endswith(".json") else text)
            for name, text in files.items() if "calc" in name}


class MissingCalculationLowering(Exception):
    """The compiler refuses the module form: a derived value or a parameter is not lowered yet."""


def lowered(pack_dir: Path) -> dict:
    """calc_ir of a pack whose calculation is (partly) a module form."""
    try:
        return calc_ir(pack_dir)
    except pack.CompileError as error:
        raise MissingCalculationLowering(str(error)) from error


def form(pack_dir: Path, decls: list, name: str = "calculation") -> None:
    """A module form with header-only text, declared in pack.yaml beside the pack's other modules."""
    meta_path = pack_dir / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    body = {"rezono": "0", "pack": meta["name"], "use": [], "decls": decls}
    spans = [{"at": at, "line": "3", "start": "0", "end": "1"} for at in rezono_module.place_pointers(body)]
    (pack_dir / "rezono").mkdir(exist_ok=True)
    (pack_dir / "rezono" / f"{name}.json").write_text(
        json.dumps({"format": "rezono.module/2", "module": body, "spans": spans}, sort_keys=True), encoding="utf-8")
    (pack_dir / "rezono" / f"{name}.rezono").write_text(f"rezono 0\npack {meta['name']}\n", encoding="utf-8")
    entry = {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "conclusions"}
    meta["rezono"] = [e for e in meta.get("rezono") or [] if e["module"] != entry["module"]] + [entry]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def path(*names: str) -> dict:
    return {"path": list(names)}


def lit(value: str) -> dict:
    return {"lit": value}


def row_parameter(name: str, kind: str = "SchemeParameter", slot: str = "value", by: str = "name") -> dict:
    return {"param": name, "type": "Int", "source": {"kind": kind, "slot": slot, "nameSlot": by}}


def derived(name: str, *definitions: dict, version: str = "2026", valid=("2026-01-01", "2027-01-01"),
            known: str = "2025-12-09") -> dict:
    """A derived value in cents with one version and its definitions, as the section Versions with
    definitions writes it."""
    return {"derived": name, "type": "Int", "output": {"relation": name, "slot": "cents"}, "unit": "cents",
            "versions": [{"version": version, "valid": list(valid), "known": known,
                          "definitions": list(definitions)}]}


def definition(name: str, when: dict, value: dict) -> dict:
    return {"name": name, "when": when, "value": value}
