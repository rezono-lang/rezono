"""Shared helper for staged candidate whole-pack acceptance tests.

Each ready pack stages its Rezono modules under `<pack>/candidate/` (`*.rezono` and their generated `*.json`
forms) without altering the live pack's hash or import pins (decisions/language-standard-pack-candidates.md).
Both isolated copies (legacy vs candidate) are compiled in `tmp_path` and compared on schema model, semantic
schema bundle, and compiled rule IR.
"""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from model_parity import legacy_helpers
from rezono_compiler import emit, pack


REPO = Path(__file__).resolve().parents[3]
READER = REPO / "rezono" / "src" / "write-form.ts"


class MissingStagedCandidate(AssertionError):
    """The pack does not yet have a staged candidate under `<pack>/candidate/`."""


def _copy_isolated(tmp_path: Path, pack_rel: str, form: str) -> Path:
    root = tmp_path / form
    legacy_helpers().materialize_legacy_packs(root, ("packs", pack_rel))
    target = root / pack_rel
    source = REPO / pack_rel
    if (source / "facts").is_dir() and not (target / "facts").exists():
        shutil.copytree(source / "facts", target / "facts")
    if form == "legacy":
        return target

    candidate_dir = source / "candidate"
    if not candidate_dir.is_dir():
        raise MissingStagedCandidate(f"{pack_rel}/candidate/ does not exist yet")
    rezono_files = sorted(candidate_dir.rglob("*.rezono"))
    if not rezono_files:
        raise MissingStagedCandidate(f"{pack_rel}/candidate/ contains no .rezono modules")

    schema_layers: dict[str, str] = {}
    if (target / "schema").is_dir():
        for schema_path in sorted((target / "schema").rglob("*.yaml")):
            doc = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
            layer = (doc.get("annotations") or {}).get("layer")
            if isinstance(layer, str):
                mod = schema_path.relative_to(target / "schema").with_suffix("").as_posix()
                schema_layers[mod] = layer

    shutil.rmtree(target / "schema", ignore_errors=True)
    shutil.rmtree(target / "rules", ignore_errors=True)
    shutil.rmtree(target / "rezono", ignore_errors=True)
    shutil.copytree(candidate_dir, target / "rezono")

    entries = []
    node = os.environ.get("REZONO_NODE", "node")
    stage = tmp_path / "regenerated"
    stage.mkdir(parents=True, exist_ok=True)
    for rezono_path in rezono_files:
        rel_mod = rezono_path.relative_to(candidate_dir).with_suffix("").as_posix()
        form_path = rezono_path.with_suffix(".json")
        if not form_path.is_file():
            raise AssertionError(f"missing generated form {pack_rel}/candidate/{rel_mod}.json")
        stem = rel_mod.replace("/", "_")
        lf_source = stage / f"{stem}.rezono"
        lf_source.write_bytes(rezono_path.read_bytes().replace(b"\r\n", b"\n"))
        regenerated = stage / f"{stem}.json"
        result = subprocess.run(
            [node, str(READER), str(lf_source), str(regenerated)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, f"reader failed on {rel_mod}.rezono:\n{result.stderr or result.stdout}"
        actual = regenerated.read_bytes().replace(b"\r\n", b"\n")
        expected = form_path.read_bytes().replace(b"\r\n", b"\n")
        assert actual == expected, (
            f"{pack_rel}/candidate/{rel_mod}.json does not match write-form.ts output"
        )
        entries.append({
            "module": f"rezono/{rel_mod}.rezono",
            "form": f"rezono/{rel_mod}.json",
            "layer": schema_layers.get(rel_mod, "facts"),
        })

    meta_path = target / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    meta["rezono"] = entries
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return target


def _strip_own_spans(value, own_prefix: str):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in {"span", "origin"} and isinstance(item, dict):
                file_name = str(item.get("file", ""))
                if file_name.startswith(("schema/", "rules/", "rezono/", f"{own_prefix}:")):
                    continue
            out[key] = _strip_own_spans(item, own_prefix)
        return out
    if isinstance(value, list):
        return [_strip_own_spans(item, own_prefix) for item in value]
    return value


def _semantic_bundle(bundle: dict, pack_name: str) -> dict:
    cleaned = deepcopy(bundle)
    cleaned.pop("schemas", None)
    cleaned.pop("rules", None)
    return _strip_own_spans(cleaned, pack_name)


def _semantic_rules(ir: dict) -> dict:
    rules = []
    for entry in ir.get("rules", []):
        rules.append({
            key: value
            for key, value in entry.items()
            if key not in {"id", "origin", "span", "witness"}
        })
    rules.sort(key=lambda r: json.dumps(r, sort_keys=True))
    relations = sorted(ir.get("relations", []), key=lambda r: r["name"])
    invariants = sorted(ir.get("invariants", []), key=lambda inv: json.dumps(inv, sort_keys=True))
    return {"format": ir.get("format"), "relations": relations, "invariants": invariants, "rules": rules}


def compile_isolated(tmp_path: Path, pack_rel: str, form: str) -> tuple[pack.Pack, dict[str, bytes]]:
    directory = _copy_isolated(tmp_path, pack_rel, form)
    with ExitStack() as stack:
        legacy_helpers().admit_legacy_std_packs(stack, tmp_path / form)
        model = pack.read(directory)
        files = emit.compile_pack(model)
    return model, files


def assert_legacy_oracle(tmp_path: Path, pack_rel: str) -> None:
    model, files = compile_isolated(tmp_path, pack_rel, "legacy")
    bundle = json.loads(files["bundle/schema-bundle.json"])
    ir = json.loads(files["ir/rules.json"])
    assert model.kinds, f"{pack_rel} must declare kinds"
    assert bundle["kinds"], f"{pack_rel} bundle must include kinds"
    assert ir["rules"], f"{pack_rel} must compile rules"


def assert_staged_candidate_matches_legacy(tmp_path: Path, pack_rel: str) -> None:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from scripts import convert_pack

    legacy_model, legacy_files = compile_isolated(tmp_path, pack_rel, "legacy")
    candidate_model, candidate_files = compile_isolated(tmp_path, pack_rel, "candidate")

    convert_pack.compare(legacy_model, candidate_model)
    pack_name = str(legacy_model.meta["name"])
    assert _semantic_bundle(json.loads(candidate_files["bundle/schema-bundle.json"]), pack_name) == (
        _semantic_bundle(json.loads(legacy_files["bundle/schema-bundle.json"]), pack_name)
    )
    assert _semantic_rules(json.loads(candidate_files["ir/rules.json"])) == (
        _semantic_rules(json.loads(legacy_files["ir/rules.json"]))
    )
