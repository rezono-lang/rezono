"""Author small packs for the expression-contract tests and compile them on the ordinary path."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from rezono_compiler import emit, pack
from support import FIXTURE


ROOT = Path(__file__).resolve().parents[3]

# A closed kind with an optional integer scalar and a multivalued reference, in the fixture's LinkML style.
STAGE_SCHEMA = """id: https://rezono.example/stages
name: stages
imports:
  - linkml:types
default_range: string
annotations:
  layer: facts
classes:
  Stage:
    attributes:
      id:
        identifier: true
      rank:
        range: integer
      next:
        range: Stage
        multivalued: true
"""


def stage_pack(tmp_path: Path, name: str = "minimal") -> Path:
    """Copy the neutral fixture and add the stage schema."""
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name))
    (directory / "schema/stages.yaml").write_text(STAGE_SCHEMA, encoding="utf-8", newline="\n")
    return directory


def author(directory: Path, stem: str, source: str) -> dict:
    """Write an authored module and its form with the packaged reader; return its pack.yaml registration."""
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    path = folder / f"{stem}.rezono"
    form = path.with_suffix(".json")
    path.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(path), str(form)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(form.read_bytes())["format"] == "rezono.module/3"
    return {"module": f"rezono/{path.name}", "form": f"rezono/{form.name}", "layer": "facts"}


def register(directory: Path, *modules: dict) -> None:
    path = directory / "pack.yaml"
    metadata = yaml.safe_load(path.read_text(encoding="utf-8"))
    metadata["rezono"] = list(modules)
    path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8", newline="\n")


def compile_rules(directory: Path) -> dict:
    """The rule IR of the ordinary pack compiler."""
    files = emit.compile_pack(pack.read(directory))
    return json.loads(files["ir/rules.json"])


def refusals(directory: Path) -> list[tuple[str, str]]:
    """The code and JSON pointer of each diagnostic the ordinary compiler reports."""
    with pytest.raises(pack.CompileError) as refused:
        compile_rules(directory)
    return [(item.code, item.where.partition("#")[2]) for item in refused.value.diagnostics]


def literals(rule: dict) -> list[tuple[str, str, list[str]]]:
    return [(item["polarity"], item["relation"], item["terms"]) for item in rule["body"]]


ORDER_CHECK = Path(__file__).resolve().parent / "fixtures" / "order-check"


def order_check_pack(tmp_path: Path, representation: str) -> Path:
    """Assemble the acceptance pack of decisions/language-expression-semantics.md §5 next to the real std-order.

    `representation` is `legacy` (Datalog rules), `native` (the authored module) or `rejected` (the native
    module with `not zero(x)`). The facts, role grant and messages are shared.
    """
    from rezono_compiler import modules

    root = tmp_path / representation
    std = Path(shutil.copytree(ROOT / "packs/std-order", root / "std-order"))
    directory = Path(shutil.copytree(ORDER_CHECK / "common", root / "order-check"))
    shutil.copytree(ORDER_CHECK / representation, directory, dirs_exist_ok=True)
    metadata = {
        "name": "order-check", "version": "0", "default_language": "en",
        "imports": [{"name": "std-order", "path": "../std-order", "sha256": modules.pack_hash(std)}],
    }
    module = directory / "rezono/order.rezono"
    if module.is_file():
        registration = author(directory, "order", module.read_text(encoding="utf-8"))
        metadata["rezono"] = [registration]
    (directory / "pack.yaml").write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8", newline="\n")
    return directory
