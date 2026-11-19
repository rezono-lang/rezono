"""Helpers for staged candidate whole-pack acceptance tests (decisions/language-standard-pack-candidates.md)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import yaml

from rezono_compiler import batch, emit, pack, rules as ir


REPO = Path(__file__).resolve().parents[3]
WRITE_FORM = REPO / "rezono/src/write-form.ts"


class MissingCandidatePack(AssertionError):
    """The staged candidate module or form is missing or disagrees with the live legacy pack."""


def unplaced(value, pack_name: str, sources: set[str]):
    """Normalise source file names and spans belonging to the converted pack while keeping schema identity."""
    if isinstance(value, dict):
        if value.get("file") in sources and set(value) <= {"file", "line", "column"}:
            return {"file": pack_name}
        return {
            key: (pack_name if key == "file" and item in sources else unplaced(item, pack_name, sources))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [unplaced(item, pack_name, sources) for item in value]
    return value


def verify_candidate_forms(pack_dir: Path, modules: tuple[str, ...], tmp_path: Path) -> None:
    """Require each staged module and form to exist and match what rezono/src/write-form.ts generates."""
    candidate_dir = pack_dir / "candidate"
    for name in modules:
        source = candidate_dir / f"{name}.rezono"
        form = candidate_dir / f"{name}.json"
        if not source.is_file() or not form.is_file():
            raise MissingCandidatePack(f"missing staged candidate file: {source.relative_to(REPO)} or {form.relative_to(REPO)}")
    node = os.environ.get("REZONO_NODE", "node")
    stage = tmp_path / "regenerated"
    stage.mkdir(parents=True, exist_ok=True)
    for name in modules:
        source = candidate_dir / f"{name}.rezono"
        form = candidate_dir / f"{name}.json"
        lf_source = stage / f"{name}.rezono"
        lf_source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        out = stage / f"{name}.json"
        result = subprocess.run([node, str(WRITE_FORM), str(lf_source), str(out)],
                                capture_output=True, encoding="utf-8", check=False)
        if result.returncode:
            raise MissingCandidatePack(f"write-form.ts refused {source.relative_to(REPO)}:\n{result.stderr or result.stdout}")
        actual = out.read_bytes().replace(b"\r\n", b"\n")
        expected = form.read_bytes().replace(b"\r\n", b"\n")
        if actual != expected:
            raise MissingCandidatePack(f"{form.relative_to(REPO)} does not match write-form.ts output for {name}.rezono")


def isolated_standard_pack(pack_dir: Path, tmp_path: Path, form: str, module_name: str, layer: str = "facts") -> Path:
    """Build an isolated copy of a standard pack in either its legacy or staged candidate form."""
    target = tmp_path / form / pack_dir.name
    shutil.copytree(pack_dir, target, ignore=shutil.ignore_patterns("candidate"))
    if form == "legacy":
        return target
    verify_candidate_forms(pack_dir, (module_name,), tmp_path)
    shutil.rmtree(target / "schema", ignore_errors=True)
    shutil.rmtree(target / "rules", ignore_errors=True)
    shutil.copytree(pack_dir / "candidate", target / "rezono")
    meta_path = target / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    meta["rezono"] = [{"module": f"rezono/{module_name}.rezono", "form": f"rezono/{module_name}.json", "layer": layer}]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return target


def compiled_meaning(pack_dir: Path, pack_name: str, module_name: str) -> dict:
    """Compile an isolated standard pack and return its normalised bundle, IR and SQL outputs."""
    model = pack.read(pack_dir)
    files = emit.compile_pack(model)
    names = (f"schema/{module_name}.yaml", f"rules/{module_name}.dl", f"rezono/{module_name}.rezono")
    sources = set(names) | {f"{pack_name}{sep}{item}" for item in names for sep in "/:"}
    return {
        "files": sorted(files),
        "bundle": unplaced(json.loads(files["bundle/schema-bundle.json"]), pack_name, sources),
        "ir": unplaced(json.loads(files["ir/rules.json"]), pack_name, sources),
        "tables_sql": files["engine/tables.sql"],
        "integrity_sql": files["engine/integrity.sql"],
        "rules_sql": files["engine/rules.sql"],
        "batch_sql": files["batch/rules.sql"],
        "parameters": files["engine/parameters.json"],
        "pipelines": files["engine/pipelines.json"],
    }


def evaluate_batch(pack_dir: Path, tables: dict[str, list[tuple]]) -> dict[str, set[tuple[str, ...]]]:
    """Run the DuckDB batch backend on the pack's compiled rules over the supplied base tables."""
    prog = ir.load(pack.read(pack_dir).rules)
    con = batch.connect(prog, {name: sorted(rows) for name, rows in tables.items()})
    batch.compute(con, prog)
    return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in batch.read(con, prog).items()}
