#!/usr/bin/env python3
"""Production CI discovery and coordinator state entrypoint over the pinned build pack.

Reads ``build/engine-pin.yaml`` via ``loop.build_pinned_runner``, validates that the
pinned earlier ``main`` engine commit is distinct from the candidate commit and an
ancestor of ``main``, compiles/publishes/checks ``build/pack.yaml`` strictly from
that pinned engine checkout, and projects verified publications through:

- ``loop.build_cutover.select_suites`` for CI suite selection (fail-closed safe mode
  selecting every suite in the universe on engine failure or absent/rejected
  publication; never falling back to ``components.py ci-matrix``).
- ``loop.build_coordinator_reader.read_coordinator_state`` for coordinator task and
  claim-release state (fail-closed safe mode assigning no new tasks and keeping all
  claims intact on engine failure or absent/rejected publication).
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loop.build_coordinator_reader import read_coordinator_state
from loop.build_cutover import select_suites
from loop.build_pinned_runner import read_engine_pin, validate_engine_pin
from scripts.components import (
    SHARDS,
    Component,
    discover_components,
    discover_python_packages,
)

ENGINE_PIN_REL = "build/engine-pin.yaml"
BUILD_PACK_MANIFEST = "build/pack.yaml"
DEFAULT_MAIN_REF = "refs/remotes/origin/main"
DEFAULT_RUN_ID = "current"
PINNED_TIMEOUT_SECONDS = 180

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40

_PINNED_ARCHIVE_PATHS = (
    "canon",
    "compiler",
    "checker",
    "edge/publisher",
    "admission",
    "publication",
    "contracts",
    "packs",
    "build",
    "rezono",
)
_PINNED_PYTHON_DIRS = (
    "canon",
    "compiler",
    "checker",
    "edge/publisher",
    "admission",
    "publication",
    "contracts/python",
)

_PINNED_WORKER_SCRIPT = r"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

import yaml

pinned_root = Path(sys.argv[1]).resolve()
payload_path = Path(sys.argv[2]).resolve()
result_path = Path(sys.argv[3]).resolve()

pinned_sys_paths = [str(pinned_root / "_pinned_meta")] + [
    str(pinned_root / rel)
    for rel in (
        "canon",
        "compiler",
        "checker",
        "edge/publisher",
        "admission",
        "publication",
        "contracts/python",
    )
    if (pinned_root / rel).is_dir()
]
sys.path[:0] = pinned_sys_paths

import rezono_checker
import rezono_compiler
import rezono_publisher
from rezono_checker.rules import derived_relations, load_rules, load_seals
from rezono_compiler import pack as compiler_pack
from rezono_publisher import batch, publish, store

for module in (rezono_compiler, rezono_publisher, rezono_checker):
    origin = getattr(module, "__file__", None)
    if not origin or not Path(origin).resolve().is_relative_to(pinned_root):
        raise RuntimeError(f"refusing to run non-pinned engine module {module.__name__} from {origin!r}")

payload = json.loads(payload_path.read_text(encoding="utf-8"))
build_dir = pinned_root / "build"
if not (build_dir / "pack.yaml").is_file():
    raise FileNotFoundError("pinned checkout is missing build/pack.yaml")

# Verify the pinned pack compiles cleanly via rezono_compiler before publishing.
compiler_pack.read(build_dir)

facts_dir = build_dir / "facts"
facts_dir.mkdir(exist_ok=True)
(facts_dir / "input.yaml").write_text(
    yaml.safe_dump(payload["records"], sort_keys=True),
    encoding="utf-8",
)
sources_sidecar = payload.get("sources_sidecar")
if sources_sidecar is not None:
    (facts_dir / "input.sources.yaml").write_text(
        yaml.safe_dump(sources_sidecar, sort_keys=True),
        encoding="utf-8",
    )

archive_dir = pinned_root / "archive"
archive = store.FileStore(archive_dir)
handoff = {}
evidence_dir_raw = payload.get("evidence_dir")
if evidence_dir_raw:
    evidence_dir = Path(evidence_dir_raw)
    if (evidence_dir / "archive").is_dir():
        for src in sorted((evidence_dir / "archive").rglob("*")):
            if src.is_file():
                rel = src.relative_to(evidence_dir / "archive").as_posix()
                archive.put_new(rel, src.read_bytes())
    context_file = evidence_dir / "context.json"
    index_file = evidence_dir / "index.json"
    if context_file.is_file() and index_file.is_file():
        from rezono_publisher.evidence import Evidence

        ctx_bytes = context_file.read_bytes()
        idx_bytes = index_file.read_bytes()
        archive.put_new("observations/context.json", ctx_bytes)
        archive.put_new("observations/index.json", idx_bytes)
        handoff["evidence"] = Evidence(
            context_uri=archive.uri("observations/context.json"),
            context_sha256=hashlib.sha256(ctx_bytes).hexdigest(),
            index_uri=archive.uri("observations/index.json"),
            index_sha256=hashlib.sha256(idx_bytes).hexdigest(),
            store=archive,
        )

knowledge_time = payload["knowledge_time"]
source_entries = [tuple(item) for item in payload.get("epoch_sources", [["facts", "input"]])]
epoch = batch.epoch(
    build_dir,
    epoch=1,
    knowledge_time=knowledge_time,
    sources=source_entries,
    **handoff,
)

role_name = payload.get("role", "reader")
role_mode = payload.get("role_mode", "complete")
manifest = publish.publish(epoch, archive, {role_name: role_mode})

def read_archive_uri(uri: str) -> bytes:
    prefix = archive.uri("")
    if not uri.startswith(prefix):
        raise ValueError(f"unexpected archive URI outside store: {uri!r}")
    return archive.get(uri.removeprefix(prefix))

# Independently verify every published witness document via rezono_checker.
rules_doc = json.loads(epoch.rules)
rules_obj = load_rules(rules_doc)
derived = derived_relations(rules_doc, rules_obj)
seals = load_seals(rules_doc)
checker_valid = True
witness_entries = [entry for entry in manifest.get("witnesses", []) if entry.get("role") == role_name]
if not witness_entries:
    checker_valid = False
for entry in witness_entries:
    raw = read_archive_uri(entry["uri"])
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"witness digest mismatch for {entry['uri']}")
    proof_doc = json.loads(raw)
    report = rezono_checker.check_epoch(
        proof_doc["witnesses"],
        manifest,
        rules_obj,
        read_archive_uri,
        derived=derived,
        seals=seals,
        evidence=handoff.get("evidence"),
    )
    if not report.get("valid"):
        checker_valid = False

rows: dict[str, list[dict]] = {}
for entry in manifest.get("snapshots", []):
    if entry.get("role") != role_name:
        continue
    raw = read_archive_uri(entry["uri"])
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"snapshot digest mismatch for {entry['relation']}")
    rows[entry["relation"]] = json.loads(raw)

checks = [dict(c) for c in manifest.get("checks", []) if isinstance(c, dict)]
if not checker_valid:
    checks.append({"name": "rezono:proofs", "status": "red", "violations": 1})

if not any(c.get("name") == "rezono:schema" for c in checks):
    schema_checks = [
        c for c in checks
        if isinstance(c.get("name"), str) and not c["name"].startswith("rezono:")
    ]
    schema_ok = bool(schema_checks) and all(
        c.get("status") == "green" and c.get("violations", 0) == 0
        for c in schema_checks
    )
    checks.append({
        "name": "rezono:schema",
        "status": "green" if schema_ok else "red",
        "violations": 0 if schema_ok else 1,
    })

verified_manifest = {**manifest, "checks": checks}
result_path.write_text(
    json.dumps({"manifest": verified_manifest, "rows": rows}, sort_keys=True),
    encoding="utf-8",
)
"""


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def _git_text(root: Path, *args: str) -> str:
    return _git(root, *args).decode("utf-8").strip()


def _test_files(root: Path, folder: str) -> list[str]:
    directory = root / folder
    if not directory.is_dir():
        return []
    return sorted({
        path.relative_to(root).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in directory.rglob(pattern)
        if path.is_file() and "node_modules" not in path.relative_to(directory).parts
    })


def _shard_count(root: Path, folder: str) -> int:
    files = _test_files(root, folder)
    return min(SHARDS.get(folder, 1), max(1, len(files)))


def _write_pinned_metadata(pinned_root: Path) -> None:
    """Create isolated PEP 566 .dist-info metadata from pinned pyproject.toml files."""
    meta_dir = pinned_root / "_pinned_meta"
    meta_dir.mkdir(exist_ok=True)
    for rel in _PINNED_PYTHON_DIRS:
        pyproject = pinned_root / rel / "pyproject.toml"
        if not pyproject.is_file():
            continue
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        name = project.get("name")
        if not isinstance(name, str) or not name:
            continue
        version = str(project.get("version", "0.0.0"))
        dist_dir = meta_dir / f"{name.replace('-', '_')}-{version}.dist-info"
        dist_dir.mkdir(exist_ok=True)
        lines = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
        for dep in project.get("dependencies", []):
            if isinstance(dep, str) and dep:
                lines.append(f"Requires-Dist: {dep}")
        (dist_dir / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _extract_pinned_engine(root: Path, engine_sha: str, target_dir: Path) -> None:
    """Extract only pinned engine and pack directories from ``engine_sha`` via ``git archive``."""
    available: list[str] = []
    for rel in _PINNED_ARCHIVE_PATHS:
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"{engine_sha}:{rel}"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            available.append(rel)
    if "build" not in available or "compiler" not in available or "edge/publisher" not in available:
        raise ValueError(f"pinned commit {engine_sha} is missing required engine or build/ paths")
    archive_bytes = _git(root, "archive", engine_sha, "--", *available)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
        tar.extractall(target_dir, filter="data")
    if not (target_dir / BUILD_PACK_MANIFEST).is_file():
        raise ValueError(f"pinned commit {engine_sha} is missing {BUILD_PACK_MANIFEST}")
    _write_pinned_metadata(target_dir)


def _format_utc(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pinned_build_pack(
    *,
    root: Path,
    records: Mapping[str, Any],
    sources_sidecar: Mapping[str, Any] | None,
    knowledge_time: str,
    pin_path: Path | None = None,
    candidate_sha: str | None = None,
    main_ref: str = DEFAULT_MAIN_REF,
    role: str = "reader",
    role_mode: str = "complete",
    evidence_dir: Path | None = None,
    timeout_seconds: int = PINNED_TIMEOUT_SECONDS,
) -> tuple[str | None, dict[str, Any] | None, dict[str, list[dict[str, Any]]] | None, str | None]:
    """Read and validate the engine pin, then compile/publish/check ``build/pack.yaml`` on it.

    Returns ``(engine_sha, manifest, rows, engine_error)``. Any pin, checkout, compile,
    publish, or checker failure returns ``engine_error`` instead of raising so callers
    enter fail-closed safe mode through ``select_suites`` or ``read_coordinator_state``.
    """
    resolved_pin = pin_path if pin_path is not None else root / ENGINE_PIN_REL
    engine_sha: str | None = None
    try:
        engine_sha = read_engine_pin(resolved_pin)
        candidate = candidate_sha or _git_text(root, "rev-parse", "HEAD")
        validate_engine_pin(
            root=root,
            engine_sha=engine_sha,
            candidate_sha=candidate,
            main_ref=main_ref,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return engine_sha, None, None, f"engine pin validation failed: {exc}"

    try:
        with tempfile.TemporaryDirectory(prefix="rezono-pinned-build-") as tmp:
            work = Path(tmp)
            pinned_root = work / "engine"
            pinned_root.mkdir()
            _extract_pinned_engine(root, engine_sha, pinned_root)

            payload_path = work / "payload.json"
            result_path = work / "result.json"
            payload: dict[str, Any] = {
                "records": records,
                "sources_sidecar": sources_sidecar,
                "knowledge_time": knowledge_time,
                "role": role,
                "role_mode": role_mode,
                "epoch_sources": [["facts", "input"]],
            }
            if evidence_dir is not None:
                payload["evidence_dir"] = str(evidence_dir)
            payload_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, "-P", "-c", _PINNED_WORKER_SCRIPT, str(pinned_root), str(payload_path), str(result_path)],
                cwd=pinned_root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            if proc.returncode != 0 or not result_path.is_file():
                detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
                first_line = detail.splitlines()[-1] if detail else f"exit {proc.returncode}"
                return engine_sha, None, None, f"pinned engine execution failed: {first_line}"

            output = json.loads(result_path.read_text(encoding="utf-8"))
            manifest = output.get("manifest")
            rows = output.get("rows")
            if not isinstance(manifest, dict) or not isinstance(rows, dict):
                return engine_sha, None, None, "pinned engine returned malformed publication payload"
            return engine_sha, manifest, rows, None
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError, json.JSONDecodeError) as exc:
        return engine_sha, None, None, f"pinned engine execution failed: {exc}"


def _resolve_git_range(
    root: Path,
    *,
    event_name: str,
    base_ref: str,
    before_sha: str,
    merge_group_base: str,
    merge_group_head: str,
) -> tuple[str, str, str, list[str], int]:
    """Return ``(build_event, base_sha, head_sha, changed_paths, observed_at)``."""
    head_sha = _git_text(root, "rev-parse", "HEAD")
    if not _SHA40.fullmatch(head_sha):
        raise ValueError(f"HEAD is not a 40-hex commit SHA: {head_sha!r}")
    observed_at = int(_git_text(root, "show", "-s", "--format=%ct", head_sha))

    if event_name == "merge_group":
        if not (_SHA40.fullmatch(merge_group_base) and _SHA40.fullmatch(merge_group_head)):
            raise ValueError("merge_group event lacks valid 40-hex base/head SHAs")
        if head_sha != merge_group_head:
            raise ValueError("HEAD does not match MERGE_GROUP_HEAD_SHA")
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", merge_group_base, merge_group_head],
            cwd=root,
            check=True,
            capture_output=True,
        )
        base_sha = merge_group_base
        build_event = "merge_group"
    elif event_name == "pull_request" and base_ref:
        bases = _git_text(root, "merge-base", "--all", f"origin/{base_ref}", head_sha).split()
        if len(bases) != 1 or not _SHA40.fullmatch(bases[0]):
            raise ValueError(f"ambiguous merge-base for pull request against origin/{base_ref}")
        base_sha = bases[0]
        build_event = "pull_request"
    else:
        build_event = "merge_group"
        if _SHA40.fullmatch(before_sha) and before_sha != _ZERO_SHA:
            base_sha = before_sha
        else:
            parent_probe = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD^"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            base_sha = parent_probe.stdout.strip() if parent_probe.returncode == 0 else head_sha

    raw_paths = _git(root, "diff", "--no-renames", "--name-only", "-z", base_sha, head_sha, "--")
    changed_paths = [os.fsdecode(item) for item in raw_paths.split(b"\0") if item]
    return build_event, base_sha, head_sha, changed_paths, observed_at


def capture_ci_records(
    *,
    root: Path,
    run_id: str,
    build_event: str,
    base_sha: str,
    head_sha: str,
    engine_sha: str,
    observed_at: int,
    components: Sequence[Component],
    changed_paths: Sequence[str],
    repository_name: str = "rezono-lang/rezono",
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build typed ``build/`` observation records and Git provenance sidecar for one CI run."""
    records: dict[str, list[dict[str, Any]]] = {
        "build_run": [{
            "id": run_id,
            "event": build_event,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "engine_sha": engine_sha,
            "observed_at": observed_at,
        }],
        "build_component": [
            {"id": comp.folder, "run": run_id, "kind": comp.kind, "folder": comp.folder}
            for comp in components
        ],
        "build_test_file": [
            {"id": f"tf-{comp.folder}-{idx}", "component": comp.folder, "path": rel}
            for comp in components
            for idx, rel in enumerate(_test_files(root, comp.folder), start=1)
        ],
        "build_path": [
            {"id": f"path-{idx}", "run": run_id, "path": path, "coverage": "unknown"}
            for idx, path in enumerate(changed_paths, start=1)
        ],
    }
    sources_sidecar = {
        "default": {
            "kind": "git",
            "name": repository_name,
            "revision": head_sha,
            "position": f"{base_sha}..{head_sha}",
        }
    }
    return records, sources_sidecar


def expand_matrix(
    *,
    root: Path,
    components: Sequence[Component],
    selected_folders: Iterable[str],
) -> dict[str, Any]:
    """Expand selected component folders into the GitHub Actions CI matrix payload."""
    selected = set(selected_folders)
    active = [comp for comp in components if comp.folder in selected]
    py_items = [
        {
            "folder": comp.folder,
            "kind": comp.kind,
            "shard": shard,
            "total": total,
            "label": comp.folder if total == 1 else f"{comp.folder} {shard + 1}/{total}",
        }
        for comp in active
        if comp.kind in ("contracts", "python")
        for total in [_shard_count(root, comp.folder)]
        for shard in range(total)
    ]
    node_items = [
        {
            "folder": comp.folder,
            "kind": comp.kind,
            "pytest": bool(_test_files(root, comp.folder)),
        }
        for comp in active
        if comp.kind == "node"
    ]
    pytest_items = py_items + [
        {
            "folder": item["folder"],
            "kind": "node",
            "shard": 0,
            "total": 1,
            "label": item["folder"],
        }
        for item in node_items
        if item["pytest"]
    ]
    editable_flags = " ".join(f"-e {pkg}" for pkg in discover_python_packages(root))
    return {
        "python": py_items,
        "has_python": bool(py_items),
        "node": node_items,
        "has_node": bool(node_items),
        "pytest": pytest_items,
        "has_pytest": bool(pytest_items),
        "python_editable": editable_flags,
    }


def discover_ci_matrix(
    *,
    root: Path = ROOT,
    run_id: str = DEFAULT_RUN_ID,
    event_name: str = "",
    base_ref: str = "",
    before_sha: str = "",
    merge_group_base: str = "",
    merge_group_head: str = "",
    pin_path: Path | None = None,
    main_ref: str = DEFAULT_MAIN_REF,
    records_override: Mapping[str, Any] | None = None,
    evidence_dir: Path | None = None,
    repository_name: str = "rezono-lang/rezono",
) -> dict[str, Any]:
    """Execute ``build/`` on the pinned earlier main engine and project CI matrix outputs."""
    pull_request = event_name == "pull_request"
    components = discover_components(root, keep_invalid_node=pull_request)
    universe = [comp.folder for comp in components]

    engine_sha: str | None = None
    manifest: dict[str, Any] | None = None
    rows: dict[str, list[dict[str, Any]]] | None = None
    engine_error: str | None = None

    resolved_pin = pin_path if pin_path is not None else root / ENGINE_PIN_REL
    try:
        engine_sha = read_engine_pin(resolved_pin)
        if records_override is not None:
            head_sha = _git_text(root, "rev-parse", "HEAD")
            observed_at = int(_git_text(root, "show", "-s", "--format=%ct", head_sha))
            records: Mapping[str, Any] = records_override
            sources_sidecar: Mapping[str, Any] = {
                "default": {
                    "kind": "git",
                    "name": repository_name,
                    "revision": head_sha,
                    "position": head_sha,
                }
            }
        else:
            build_event, base_sha, head_sha, changed_paths, observed_at = _resolve_git_range(
                root,
                event_name=event_name,
                base_ref=base_ref,
                before_sha=before_sha,
                merge_group_base=merge_group_base,
                merge_group_head=merge_group_head,
            )
            records, sources_sidecar = capture_ci_records(
                root=root,
                run_id=run_id,
                build_event=build_event,
                base_sha=base_sha,
                head_sha=head_sha,
                engine_sha=engine_sha,
                observed_at=observed_at,
                components=components,
                changed_paths=changed_paths,
                repository_name=repository_name,
            )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        engine_error = f"observation capture failed: {exc}"
    else:
        engine_sha, manifest, rows, engine_error = run_pinned_build_pack(
            root=root,
            records=records,
            sources_sidecar=sources_sidecar,
            knowledge_time=_format_utc(observed_at),
            pin_path=resolved_pin,
            candidate_sha=head_sha,
            main_ref=main_ref,
            evidence_dir=evidence_dir,
        )

    outcome = select_suites(
        run=run_id,
        manifest=manifest,
        rows=rows,
        engine_error=engine_error,
        universe=universe,
    )
    matrix = expand_matrix(root=root, components=components, selected_folders=outcome["use"])
    return {
        "engine_sha": engine_sha,
        "engine_error": engine_error,
        "outcome": outcome,
        "matrix": matrix,
    }


def _load_publication_files(
    *,
    manifest_path: Path | None,
    rows_path: Path | None,
    archive_dir: Path | None,
    role: str,
) -> tuple[dict[str, Any] | None, dict[str, list[dict[str, Any]]] | None, str | None]:
    """Read a published manifest and verified snapshot rows from disk."""
    if manifest_path is None:
        return None, None, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return None, None, "manifest file is not a JSON object"
        if rows_path is not None:
            raw_rows = json.loads(rows_path.read_text(encoding="utf-8"))
            if not isinstance(raw_rows, dict):
                return manifest, None, "rows file is not a JSON object"
            return manifest, raw_rows, None
        if archive_dir is None:
            return manifest, None, None
        rows: dict[str, list[dict[str, Any]]] = {}
        root_dir = archive_dir.resolve()
        for entry in manifest.get("snapshots", []):
            if entry.get("role") != role:
                continue
            uri = str(entry.get("uri", ""))
            rel = uri.split("://", 1)[1].split("/", 1)[1] if "://" in uri else uri
            blob_path = (root_dir / rel).resolve()
            if not blob_path.is_relative_to(root_dir) or not blob_path.is_file():
                return manifest, None, f"snapshot missing from archive: {entry.get('relation')}"
            raw = blob_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                return manifest, None, f"snapshot digest mismatch: {entry.get('relation')}"
            rows[entry["relation"]] = json.loads(raw)
        return manifest, rows, None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, None, f"publication read failed: {exc}"


def evaluate_coordinator_state(
    *,
    root: Path = ROOT,
    run_id: str = DEFAULT_RUN_ID,
    manifest_path: Path | None = None,
    rows_path: Path | None = None,
    archive_dir: Path | None = None,
    records_path: Path | None = None,
    pin_path: Path | None = None,
    main_ref: str = DEFAULT_MAIN_REF,
    role: str = "reader",
    role_mode: str = "complete",
    knowledge_time: str = "2027-01-15T08:00:00Z",
    evidence_dir: Path | None = None,
    repository_name: str = "rezono-lang/rezono",
) -> dict[str, Any]:
    """Read coordinator task and claim-release state from a verified build publication."""
    manifest: dict[str, Any] | None = None
    rows: dict[str, list[dict[str, Any]]] | None = None
    engine_error: str | None = None

    if records_path is not None:
        try:
            records = yaml.safe_load(records_path.read_text(encoding="utf-8"))
            if not isinstance(records, Mapping):
                raise ValueError(f"records file {records_path} must contain a mapping")
            head_sha = _git_text(root, "rev-parse", "HEAD")
            sources_sidecar = {
                "default": {
                    "kind": "git",
                    "name": repository_name,
                    "revision": head_sha,
                    "position": str(records_path.name),
                }
            }
        except (OSError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
            engine_error = f"coordinator records load failed: {exc}"
        else:
            _, manifest, rows, engine_error = run_pinned_build_pack(
                root=root,
                records=records,
                sources_sidecar=sources_sidecar,
                knowledge_time=knowledge_time,
                pin_path=pin_path,
                candidate_sha=head_sha,
                main_ref=main_ref,
                role=role,
                role_mode=role_mode,
                evidence_dir=evidence_dir,
            )
    elif manifest_path is not None:
        manifest, rows, engine_error = _load_publication_files(
            manifest_path=manifest_path,
            rows_path=rows_path,
            archive_dir=archive_dir,
            role=role,
        )

    return read_coordinator_state(
        run=run_id,
        manifest=manifest,
        rows=rows,
        engine_error=engine_error,
    )


def _format_github_outputs(matrix: Mapping[str, Any]) -> list[str]:
    return [
        f"python={json.dumps(matrix['python'], separators=(',', ':'))}",
        f"has_python={'true' if matrix['has_python'] else 'false'}",
        f"node={json.dumps(matrix['node'], separators=(',', ':'))}",
        f"has_node={'true' if matrix['has_node'] else 'false'}",
        f"pytest={json.dumps(matrix['pytest'], separators=(',', ':'))}",
        f"has_pytest={'true' if matrix['has_pytest'] else 'false'}",
        f"python_editable={matrix['python_editable']}",
    ]


def _format_step_summary(result: Mapping[str, Any]) -> str:
    outcome = result["outcome"]
    engine_sha = result.get("engine_sha") or "unpinned"
    lines = [
        "### Component jobs (pinned build pack)",
        "",
        f"- Pinned engine: `{engine_sha}`",
        f"- Selection source: `{outcome['source']}`",
    ]
    if outcome["safe_mode"]:
        lines.append(f"- Safe mode reason: `{outcome['safe_mode_reason']}` (fail-closed full universe)")
        if result.get("engine_error"):
            lines.append(f"- Engine detail: `{result['engine_error']}`")
    if outcome["use"]:
        lines.extend(f"- `{folder}`" for folder in outcome["use"])
    else:
        lines.append("- none: verified build publication selected zero suites")
    return "\n".join(lines) + "\n"


def _default_root() -> Path:
    cwd = Path.cwd().resolve()
    return cwd if (cwd / ".git").exists() else ROOT


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    matrix_p = sub.add_parser("ci-matrix", help="Run pinned build/ pack and emit CI matrix outputs.")
    matrix_p.add_argument("--root", type=Path, default=None)
    matrix_p.add_argument("--run", dest="run_id", default=DEFAULT_RUN_ID)
    matrix_p.add_argument("--pin", type=Path, default=None)
    matrix_p.add_argument("--main-ref", default=DEFAULT_MAIN_REF)
    matrix_p.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    matrix_p.add_argument("--base-ref", default=os.environ.get("GITHUB_BASE_REF", ""))
    matrix_p.add_argument("--before", default=os.environ.get("GITHUB_EVENT_BEFORE", ""))
    matrix_p.add_argument("--merge-group-base", default=os.environ.get("MERGE_GROUP_BASE_SHA", ""))
    matrix_p.add_argument("--merge-group-head", default=os.environ.get("MERGE_GROUP_HEAD_SHA", ""))
    matrix_p.add_argument("--evidence-dir", type=Path, default=None)
    matrix_p.add_argument("--json", dest="as_json", action="store_true")

    coord_p = sub.add_parser("coordinator-state", help="Read coordinator state from verified build/ publication.")
    coord_p.add_argument("--root", type=Path, default=None)
    coord_p.add_argument("--run", dest="run_id", default=DEFAULT_RUN_ID)
    coord_p.add_argument("--manifest", type=Path, default=None)
    coord_p.add_argument("--rows", type=Path, default=None)
    coord_p.add_argument("--archive", type=Path, default=None)
    coord_p.add_argument("--records", type=Path, default=None)
    coord_p.add_argument("--pin", type=Path, default=None)
    coord_p.add_argument("--main-ref", default=DEFAULT_MAIN_REF)
    coord_p.add_argument("--role", default="reader")
    coord_p.add_argument("--role-mode", default="complete")
    coord_p.add_argument("--knowledge-time", default="2027-01-15T08:00:00Z")
    coord_p.add_argument("--evidence-dir", type=Path, default=None)
    coord_p.add_argument("--fail-on-safe-mode", action="store_true")

    args = parser.parse_args(argv)
    resolved_root = args.root.resolve() if args.root is not None else _default_root()
    repo_name = os.environ.get("GITHUB_REPOSITORY", "rezono-lang/rezono")

    if args.cmd == "ci-matrix":
        result = discover_ci_matrix(
            root=resolved_root,
            run_id=args.run_id,
            event_name=args.event,
            base_ref=args.base_ref,
            before_sha=args.before,
            merge_group_base=args.merge_group_base,
            merge_group_head=args.merge_group_head,
            pin_path=args.pin,
            main_ref=args.main_ref,
            evidence_dir=args.evidence_dir,
            repository_name=repo_name,
        )
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(_format_step_summary(result))
        if args.as_json:
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        lines = _format_github_outputs(result["matrix"])
        out_path = os.environ.get("GITHUB_OUTPUT")
        if out_path:
            with open(out_path, "a", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
        for line in lines:
            print(line)
        return 0

    if args.cmd == "coordinator-state":
        state = evaluate_coordinator_state(
            root=resolved_root,
            run_id=args.run_id,
            manifest_path=args.manifest,
            rows_path=args.rows,
            archive_dir=args.archive,
            records_path=args.records,
            pin_path=args.pin,
            main_ref=args.main_ref,
            role=args.role,
            role_mode=args.role_mode,
            knowledge_time=args.knowledge_time,
            evidence_dir=args.evidence_dir,
            repository_name=repo_name,
        )
        print(json.dumps(state, indent=2, sort_keys=True))
        if args.fail_on_safe_mode and state.get("safe_mode"):
            return 2
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
