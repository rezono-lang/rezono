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
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_ZERO_SHA = "0" * 40

_REQUIRED_PINNED_PATHS = (
    "build",
    "compiler",
    "edge/publisher",
    "checker",
    "canon",
    "admission",
    "contracts",
)
_OPTIONAL_PINNED_PATHS = (
    "packs",
    "publication",
    "rezono",
)
_PINNED_ARCHIVE_PATHS = (*_REQUIRED_PINNED_PATHS, *_OPTIONAL_PINNED_PATHS)
_PINNED_PYTHON_DIRS = (
    "canon",
    "compiler",
    "checker",
    "edge/publisher",
    "admission",
    "publication",
    "contracts/python",
)
_SAFE_SUBPROCESS_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "LANG",
    "LC_ALL",
    "TZ",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_PATH",
)

_PINNED_WORKER_SCRIPT = r"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

import yaml

pinned_root = Path(sys.argv[1]).resolve()
candidate_root = Path(sys.argv[2]).resolve()
payload_path = Path(sys.argv[3]).resolve()
result_path = Path(sys.argv[4]).resolve()

# Strip candidate checkout paths and editable finders before loading any rezono* package.
def _is_under_candidate(raw_path: str) -> bool:
    if not raw_path or raw_path == ".":
        return True
    try:
        resolved = Path(raw_path).resolve()
    except OSError:
        return False
    return resolved == candidate_root or resolved.is_relative_to(candidate_root)

sys.path[:] = [entry for entry in sys.path if not _is_under_candidate(entry)]
sys.meta_path[:] = [
    finder for finder in sys.meta_path
    if "editable" not in type(finder).__name__.lower()
    and "editable" not in getattr(type(finder), "__module__", "").lower()
]

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
importlib.invalidate_caches()

def _assert_all_rezono_modules_pinned() -> None:
    for name, module in list(sys.modules.items()):
        if not (name == "rezono" or name.startswith("rezono_") or name.startswith("rezono.")):
            continue
        if module is None:
            continue
        origin = getattr(module, "__file__", None)
        if origin:
            if not Path(origin).resolve().is_relative_to(pinned_root):
                raise RuntimeError(f"refusing non-pinned module {name} loaded from {origin!r}")
            continue
        paths = getattr(module, "__path__", None)
        if paths:
            for item in paths:
                if not Path(item).resolve().is_relative_to(pinned_root):
                    raise RuntimeError(f"refusing non-pinned namespace {name} with path {item!r}")
            continue
        raise RuntimeError(f"refusing rezono module {name} without pinned file or path")

import rezono_admission
import rezono_canon
import rezono_checker
import rezono_compiler
import rezono_publisher
from rezono_checker import metadata as checker_metadata
from rezono_checker.evidence import Evidence
from rezono_checker.rules import derived_relations, load_rules, load_seals
from rezono_compiler import pack as compiler_pack
from rezono_publisher import batch, publish, store

_assert_all_rezono_modules_pinned()

payload = json.loads(payload_path.read_text(encoding="utf-8"))
build_dir = pinned_root / "build"
if not (build_dir / "pack.yaml").is_file():
    raise FileNotFoundError("pinned checkout is missing build/pack.yaml")

# Compile the pinned pack via rezono_compiler before publishing.
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

def read_archive_uri(uri: str) -> bytes:
    prefix = archive.uri("")
    if not isinstance(uri, str) or not uri.startswith(prefix):
        raise ValueError(f"unexpected archive URI outside store: {uri!r}")
    data = archive.get(uri.removeprefix(prefix))
    if data is None:
        raise FileNotFoundError(f"archive object missing for {uri!r}")
    return data

handoff = {}
evidence_dir_raw = payload.get("evidence_dir")
if evidence_dir_raw:
    evidence_dir = Path(evidence_dir_raw).resolve()
    archive_src = evidence_dir / "archive"
    if archive_src.is_dir():
        for src in sorted(archive_src.rglob("*")):
            if src.is_file() and not src.is_symlink():
                rel = src.relative_to(archive_src).as_posix()
                archive.put_new(rel, src.read_bytes())

    context_key = "observations/retained/context.json"
    context_file = evidence_dir / "context.json"
    if context_file.is_file():
        ctx_bytes = context_file.read_bytes()
        archive.put_new(context_key, ctx_bytes)
    else:
        ctx_bytes = archive.get(context_key)
        if ctx_bytes is None:
            raise FileNotFoundError(f"evidence directory missing context.json and {context_key}")
    context_ref = {
        "file": context_key,
        "uri": archive.uri(context_key),
        "sha256": hashlib.sha256(ctx_bytes).hexdigest(),
    }

    index_key = "observations/submitted/index.json"
    index_file = evidence_dir / "index.json"
    candidates_ref = None
    if index_file.is_file():
        idx_bytes = index_file.read_bytes()
        archive.put_new(index_key, idx_bytes)
        candidates_ref = {
            "file": index_key,
            "uri": archive.uri(index_key),
            "sha256": hashlib.sha256(idx_bytes).hexdigest(),
        }
    else:
        idx_bytes = archive.get(index_key)
        if idx_bytes is not None:
            candidates_ref = {
                "file": index_key,
                "uri": archive.uri(index_key),
                "sha256": hashlib.sha256(idx_bytes).hexdigest(),
            }

    handoff["evidence"] = Evidence(
        context=context_ref,
        candidates=candidates_ref,
        read_bytes=read_archive_uri,
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

# Independently verify the published epoch and witness set via rezono_checker.
rules_doc = json.loads(epoch.rules)
rules_obj = load_rules(rules_doc)
derived = derived_relations(rules_doc, rules_obj)
seals = load_seals(rules_doc)
calc_doc = publish.calc_ir(epoch)
bundle_doc = json.loads(epoch.bundle) if epoch.bundle else {}
meta_kwargs = (
    {"bundle": bundle_doc, "check_metadata": epoch.check_metadata}
    if (bundle_doc.get("kinds") or epoch.check_metadata)
    else {}
)

checker_valid = True
if meta_kwargs:
    meta_errors = checker_metadata.check(meta_kwargs["bundle"], meta_kwargs["check_metadata"])
    if meta_errors:
        checker_valid = False

role_snaps = [entry for entry in manifest.get("snapshots", []) if entry.get("role") == role_name]
witness_entries = [entry for entry in manifest.get("witnesses", []) if entry.get("role") == role_name]
if not witness_entries or not role_snaps:
    checker_valid = False

role_snap_bytes: dict[str, bytes] = {}
for entry in role_snaps:
    rel = entry.get("relation")
    if not isinstance(rel, str) or not rel or rel in role_snap_bytes:
        raise ValueError(f"invalid or duplicate snapshot relation: {rel!r}")
    raw = read_archive_uri(entry["uri"])
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"snapshot digest mismatch for {rel}")
    role_snap_bytes[rel] = raw

complete_snaps = None
all_instances = None
checker_access = None
if role_mode != "complete":
    from rezono_checker import access as checker_access
    _assert_all_rezono_modules_pinned()
    complete_rows, all_instances = publish.frozen(epoch)
    complete_snaps = {rel: publish.snapshot(rs) for rel, rs in complete_rows.items()}

for entry in witness_entries:
    raw = read_archive_uri(entry["uri"])
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"witness digest mismatch for {entry['uri']}")
    proof_doc = json.loads(raw)
    calc_witnesses = proof_doc.get("calc_witnesses", ())
    if role_mode == "complete":
        role_manifest = {**manifest, "snapshots": role_snaps}
        report = rezono_checker.check_epoch(
            proof_doc["witnesses"],
            role_manifest,
            rules_obj,
            read_archive_uri,
            derived=derived,
            full=None,
            seals=seals,
            calc_witnesses=calc_witnesses,
            calc_ir=calc_doc,
            **meta_kwargs,
            evidence=handoff.get("evidence"),
        )
    else:
        claimed_full = frozenset(snap["relation"] for snap in role_snaps if snap.get("full") is True)
        verified_full, role_findings = checker_access.check_role(
            role_name,
            complete_snaps,
            role_snap_bytes,
            claimed_full,
            bundle_doc,
            rules_doc,
            calc_doc,
            all_instances,
            epoch.calc_witnesses,
            calc_witnesses,
            proof_doc["witnesses"],
        )
        if any(f.get("severity", "error") == "error" for f in role_findings):
            checker_valid = False
        role_manifest = {**manifest, "snapshots": [{**snap, "complete": True} for snap in role_snaps]}
        report = rezono_checker.check_epoch(
            proof_doc["witnesses"],
            role_manifest,
            rules_obj,
            read_archive_uri,
            derived=derived,
            full=verified_full,
            seals=(),
            calc_witnesses=calc_witnesses,
            calc_ir=calc_doc,
        )
    if not report.get("valid") or any(f.get("severity") == "error" for f in report.get("findings", [])):
        checker_valid = False

rows: dict[str, list[dict]] = {}
for rel, raw in role_snap_bytes.items():
    rows[rel] = json.loads(raw)

# Verify after the entire compile/publish/check execution that zero non-pinned rezono* modules loaded.
_assert_all_rezono_modules_pinned()

checks = [dict(c) for c in manifest.get("checks", []) if isinstance(c, dict)]
if not checker_valid:
    checks.append({"name": "rezono:proofs", "status": "red", "violations": 1})

verified_manifest = {**manifest, "checks": checks}
result_path.write_text(
    json.dumps({"manifest": verified_manifest, "rows": rows}, sort_keys=True),
    encoding="utf-8",
)
"""

_PINNED_VERIFY_SCRIPT = r"""
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

pinned_root = Path(sys.argv[1]).resolve()
candidate_root = Path(sys.argv[2]).resolve()
payload_path = Path(sys.argv[3]).resolve()
result_path = Path(sys.argv[4]).resolve()

def _is_under_candidate(raw_path: str) -> bool:
    if not raw_path or raw_path == ".":
        return True
    try:
        resolved = Path(raw_path).resolve()
    except OSError:
        return False
    return resolved == candidate_root or resolved.is_relative_to(candidate_root)

sys.path[:] = [entry for entry in sys.path if not _is_under_candidate(entry)]
sys.meta_path[:] = [
    finder for finder in sys.meta_path
    if "editable" not in type(finder).__name__.lower()
    and "editable" not in getattr(type(finder), "__module__", "").lower()
]

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
importlib.invalidate_caches()

def _assert_all_rezono_modules_pinned() -> None:
    for name, module in list(sys.modules.items()):
        if not (name == "rezono" or name.startswith("rezono_") or name.startswith("rezono.")):
            continue
        if module is None:
            continue
        origin = getattr(module, "__file__", None)
        if origin:
            if not Path(origin).resolve().is_relative_to(pinned_root):
                raise RuntimeError(f"refusing non-pinned module {name} loaded from {origin!r}")
            continue
        paths = getattr(module, "__path__", None)
        if paths:
            for item in paths:
                if not Path(item).resolve().is_relative_to(pinned_root):
                    raise RuntimeError(f"refusing non-pinned namespace {name} with path {item!r}")
            continue
        raise RuntimeError(f"refusing rezono module {name} without pinned file or path")

import duckdb
import rezono_checker
from rezono_checker import access as checker_access
from rezono_checker import metadata as checker_metadata
from rezono_checker.calc import published_views
from rezono_checker.evidence import PROTECTED as PROTECTED_RELATIONS, Evidence
from rezono_checker.rules import derived_relations, load_rules, load_seals
from rezono_compiler import __main__ as compiler_cli
from rezono_compiler import feldera_names

_assert_all_rezono_modules_pinned()

_SHA64 = re.compile(r"^[0-9a-f]{64}$")
EMPTY_RULES = '{"format":"rezono.rules/1","relations":[],"rules":[]}\n'

payload = json.loads(payload_path.read_text(encoding="utf-8"))
build_dir = pinned_root / "build"
if not (build_dir / "pack.yaml").is_file():
    raise FileNotFoundError("pinned checkout is missing build/pack.yaml")

compiled_dir = pinned_root / "_compiled"
rc = compiler_cli.main(["compile", str(build_dir), str(compiled_dir)])
if rc != 0:
    raise RuntimeError(f"pinned build/ pack compilation failed with exit {rc}")
rules_file = compiled_dir / "ir" / "rules.json"
rules_doc = json.loads(rules_file.read_text(encoding="utf-8")) if rules_file.is_file() else json.loads(EMPTY_RULES)
rules_obj = load_rules(rules_doc)
derived = derived_relations(rules_doc, rules_obj)
seals = load_seals(rules_doc)
bundle_doc = json.loads((compiled_dir / "bundle" / "schema-bundle.json").read_text(encoding="utf-8"))
calc_file = compiled_dir / "ir" / "calc.json"
calc_doc = json.loads(calc_file.read_text(encoding="utf-8")) if calc_file.is_file() else None
params_file = compiled_dir / "engine" / "parameters.json"
params_doc = json.loads(params_file.read_text(encoding="utf-8")) if params_file.is_file() else {}
tables_sql_text = (compiled_dir / "engine" / "tables.sql").read_text(encoding="utf-8")
integrity_sql_text = (compiled_dir / "engine" / "integrity.sql").read_text(encoding="utf-8")

_, _, schema_columns = checker_access._schema_from_bundle(bundle_doc, rules_doc)
calc_views = (published_views(calc_doc) | {calc_doc["as_of"]}) if calc_doc is not None else set()
known_relations = set(schema_columns) | set(derived) | set(PROTECTED_RELATIONS) | calc_views

manifest_path = Path(payload["manifest_path"]).resolve()
archive_root = Path(payload["archive_dir"]).resolve()
role_name = payload.get("role", "reader")
role_mode = payload.get("role_mode", "complete")
evidence_dir_raw = payload.get("evidence_dir")

def _uri_to_rel(uri: object) -> str:
    if not isinstance(uri, str) or not uri:
        raise ValueError(f"invalid archive URI: {uri!r}")
    if "://" in uri:
        rest = uri.split("://", 1)[1]
        if "/" not in rest:
            raise ValueError(f"invalid archive URI: {uri!r}")
        rel = rest.split("/", 1)[1]
    else:
        rel = uri
    if not rel or rel.startswith("/") or "\\" in rel or ".." in Path(rel).parts:
        raise ValueError(f"unsafe archive path: {uri!r}")
    return rel

def _resolve_under(base_dir: Path, uri: object) -> Path:
    rel = _uri_to_rel(uri)
    blob = (base_dir / rel).resolve()
    if not blob.is_relative_to(base_dir) or not blob.is_file():
        raise FileNotFoundError(f"blob missing under {base_dir.name}: {uri!r}")
    return blob

def read_archive_uri(uri: str) -> bytes:
    return _resolve_under(archive_root, uri).read_bytes()

# Trusted admission context MUST come strictly from evidence_dir, never from the untrusted archive_root.
handoff_evidence = None
evidence_invalid = False
if evidence_dir_raw:
    evidence_dir = Path(evidence_dir_raw).resolve()
    evidence_archive = (evidence_dir / "archive").resolve()
    context_key = "observations/retained/context.json"
    context_candidates = [
        evidence_dir / "context.json",
        evidence_archive / context_key,
    ]
    context_file = next(
        (p.resolve() for p in context_candidates if p.is_file() and p.resolve().is_relative_to(evidence_dir)),
        None,
    )
    if context_file is None:
        evidence_invalid = True
    else:
        ctx_bytes = context_file.read_bytes()
        ctx_uri = f"s3://rezono/{context_key}"
        trusted_blobs = {ctx_uri: ctx_bytes}
        context_ref = {
            "file": context_key,
            "uri": ctx_uri,
            "sha256": hashlib.sha256(ctx_bytes).hexdigest(),
        }
        index_key = "observations/submitted/index.json"
        index_candidates = [
            evidence_dir / "index.json",
            evidence_archive / index_key,
        ]
        index_file = next(
            (p.resolve() for p in index_candidates if p.is_file() and p.resolve().is_relative_to(evidence_dir)),
            None,
        )
        candidates_ref = None
        if index_file is not None:
            idx_bytes = index_file.read_bytes()
            idx_uri = f"s3://rezono/{index_key}"
            trusted_blobs[idx_uri] = idx_bytes
            candidates_ref = {
                "file": index_key,
                "uri": idx_uri,
                "sha256": hashlib.sha256(idx_bytes).hexdigest(),
            }
        else:
            try:
                idx_uri = f"s3://rezono/{index_key}"
                idx_bytes = read_archive_uri(idx_uri)
            except (OSError, ValueError):
                idx_bytes = None
            if idx_bytes is not None:
                candidates_ref = {
                    "file": index_key,
                    "uri": idx_uri,
                    "sha256": hashlib.sha256(idx_bytes).hexdigest(),
                }

        def _read_evidence_uri(uri: str) -> bytes:
            if uri in trusted_blobs:
                return trusted_blobs[uri]
            rel = _uri_to_rel(uri)
            if evidence_archive.is_dir():
                try:
                    return _resolve_under(evidence_archive, uri).read_bytes()
                except (OSError, ValueError):
                    pass
            # Never read retained authority blobs from the untrusted publication archive.
            if rel.startswith("observations/retained/") or rel == "context.json":
                raise FileNotFoundError(f"retained evidence blob missing from trusted evidence_dir: {uri!r}")
            return read_archive_uri(uri)

        handoff_evidence = Evidence(
            context=context_ref,
            candidates=candidates_ref,
            read_bytes=_read_evidence_uri,
        )

archive_reader = read_archive_uri

def _checks_valid(doc: dict) -> bool:
    checks = doc.get("checks")
    if not isinstance(checks, list) or not checks:
        return False
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            return False
        name = check.get("name")
        if not isinstance(name, str) or not name:
            return False
        if check.get("status") != "green":
            return False
        if "violations" in check:
            val = check["violations"]
            if type(val) is not int or val != 0:
                return False
        seen.add(name)
    return {"rezono:proofs", "rezono:schema"} <= seen

def _duckdb_sql(sql: str) -> str:
    logical = feldera_names.render(sql, feldera_names.LOGICAL)
    return logical.replace("CREATE MATERIALIZED VIEW", "CREATE VIEW").replace("CREATE LOCAL VIEW", "CREATE VIEW")

def _verify_complete_schema(complete_snaps: dict[str, bytes]) -> bool:
    if set(complete_snaps) - known_relations:
        return False
    meta_params = {
        t: [tuple(str(v) for v in r.values()) for r in rs]
        for t, rs in params_doc.items()
        if t.startswith("rezono__")
    }
    if bundle_doc.get("kinds") or meta_params:
        if checker_metadata.check(bundle_doc, meta_params):
            return False
    public_params = {
        t: sorted(tuple(str(v) for v in r.values()) for r in rs)
        for t, rs in params_doc.items()
        if not t.startswith("rezono__")
    }
    for table, expected_rows in public_params.items():
        if table not in complete_snaps:
            return False
        try:
            decoded = json.loads(complete_snaps[table])
        except (ValueError, json.JSONDecodeError):
            return False
        if not isinstance(decoded, list):
            return False
        got_rows = []
        for item in decoded:
            if not isinstance(item, dict) or not isinstance(item.get("key"), list):
                return False
            if not all(isinstance(cell, str) for cell in item["key"]):
                return False
            got_rows.append(tuple(item["key"]))
        if sorted(got_rows) != expected_rows:
            return False

    db = duckdb.connect()
    try:
        db.execute("CREATE OR REPLACE MACRO rlike(s, p) AS regexp_matches(s, p);")
        for script in (_duckdb_sql(tables_sql_text), _duckdb_sql(integrity_sql_text)):
            if "CREATE" in script:
                db.execute(script)
        base_tables = [
            row[0]
            for row in db.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_type = 'BASE TABLE' ORDER BY table_name"
            ).fetchall()
        ]
        for table in base_tables:
            quoted = '"' + table.replace('"', '""') + '"'
            if table in params_doc:
                rows_to_load = [tuple(r.values()) for r in params_doc[table]]
            else:
                if table not in complete_snaps:
                    return False
                try:
                    decoded = json.loads(complete_snaps[table])
                except (ValueError, json.JSONDecodeError):
                    return False
                if not isinstance(decoded, list):
                    return False
                rows_to_load = []
                for item in decoded:
                    if not isinstance(item, dict) or not isinstance(item.get("key"), list):
                        return False
                    if not all(isinstance(cell, str) for cell in item["key"]):
                        return False
                    rows_to_load.append(tuple(item["key"]))
            if rows_to_load:
                width = len(db.execute(f"SELECT * FROM {quoted} LIMIT 0").description)
                if any(len(r) != width for r in rows_to_load):
                    return False
                placeholders = ", ".join("?" * width)
                db.executemany(f"INSERT INTO {quoted} VALUES ({placeholders})", rows_to_load)
        if bundle_doc.get("checks"):
            counts = db.execute("SELECT info, COUNT(*) FROM validation_result GROUP BY info").fetchall()
            if any(count > 0 for _, count in counts):
                return False
        return True
    except Exception:
        return False
    finally:
        db.close()

def _read_role_snaps(snaps: list[dict]) -> dict[str, bytes] | None:
    out: dict[str, bytes] = {}
    for entry in snaps:
        if not isinstance(entry, dict):
            return None
        rel = entry.get("relation")
        expected = entry.get("sha256")
        if not isinstance(rel, str) or not rel or rel in out:
            return None
        if not isinstance(expected, str) or not _SHA64.fullmatch(expected):
            return None
        if entry.get("format") != "json":
            return None
        try:
            raw = archive_reader(entry.get("uri"))
        except (OSError, ValueError):
            return None
        if hashlib.sha256(raw).hexdigest() != expected:
            return None
        out[rel] = raw
    return out

def _read_witness_docs(entries: list[dict]) -> list[dict] | None:
    docs: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not _SHA64.fullmatch(expected):
            return None
        try:
            raw = archive_reader(entry.get("uri"))
            if hashlib.sha256(raw).hexdigest() != expected:
                return None
            doc = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(doc, dict) or not isinstance(doc.get("witnesses"), list):
            return None
        docs.append(doc)
    return docs

try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, ValueError, json.JSONDecodeError):
    manifest = None

checker_valid = (
    not evidence_invalid
    and isinstance(manifest, dict)
    and isinstance(manifest.get("id"), str)
    and bool(manifest["id"])
    and _checks_valid(manifest)
)
snapshots = manifest.get("snapshots") if checker_valid else None
witnesses = manifest.get("witnesses") if checker_valid else None
if not isinstance(snapshots, list) or not isinstance(witnesses, list):
    checker_valid = False

role_snaps = [e for e in (snapshots or []) if isinstance(e, dict) and e.get("role") == role_name]
role_witness_entries = [e for e in (witnesses or []) if isinstance(e, dict) and e.get("role") == role_name]
if not role_snaps or not role_witness_entries:
    checker_valid = False

role_snap_bytes = _read_role_snaps(role_snaps) if checker_valid else None
role_witness_docs = _read_witness_docs(role_witness_entries) if checker_valid else None
if role_snap_bytes is None or role_witness_docs is None:
    checker_valid = False
if checker_valid and (set(role_snap_bytes) - known_relations):
    checker_valid = False

if checker_valid:
    if role_mode == "complete":
        if not all(snap.get("complete") is True for snap in role_snaps):
            checker_valid = False
        elif not _verify_complete_schema(role_snap_bytes):
            checker_valid = False
        else:
            role_manifest = {**manifest, "snapshots": role_snaps}
            for proof_doc in role_witness_docs:
                calc_witnesses = proof_doc.get("calc_witnesses", ())
                try:
                    report = rezono_checker.check_epoch(
                        proof_doc["witnesses"],
                        role_manifest,
                        rules_obj,
                        archive_reader,
                        derived=derived,
                        full=None,
                        seals=seals,
                        calc_witnesses=calc_witnesses,
                        calc_ir=calc_doc,
                        evidence=handoff_evidence,
                    )
                except (KeyError, TypeError, ValueError):
                    checker_valid = False
                    break
                if not report.get("valid") or any(f.get("severity") == "error" for f in report.get("findings", [])):
                    checker_valid = False
                    break
    elif role_mode == "may_read":
        # Independently verify filtered role access via checker_access.check_role against a verified complete role.
        complete_roles = sorted({
            e.get("role") for e in snapshots
            if isinstance(e, dict) and e.get("complete") is True and isinstance(e.get("role"), str)
        })
        verified_complete = None
        for cand_role in complete_roles:
            cand_snaps = [e for e in snapshots if isinstance(e, dict) and e.get("role") == cand_role]
            cand_wits = [e for e in witnesses if isinstance(e, dict) and e.get("role") == cand_role]
            if not cand_snaps or not cand_wits or not all(s.get("complete") is True for s in cand_snaps):
                continue
            cand_snap_bytes = _read_role_snaps(cand_snaps)
            cand_wit_docs = _read_witness_docs(cand_wits)
            if cand_snap_bytes is None or cand_wit_docs is None:
                continue
            if not _verify_complete_schema(cand_snap_bytes):
                continue
            cand_manifest = {**manifest, "snapshots": cand_snaps}
            cand_ok = True
            for cdoc in cand_wit_docs:
                try:
                    creport = rezono_checker.check_epoch(
                        cdoc["witnesses"],
                        cand_manifest,
                        rules_obj,
                        archive_reader,
                        derived=derived,
                        full=None,
                        seals=seals,
                        calc_witnesses=cdoc.get("calc_witnesses", ()),
                        calc_ir=calc_doc,
                        evidence=handoff_evidence,
                    )
                except (KeyError, TypeError, ValueError):
                    cand_ok = False
                    break
                if not creport.get("valid") or any(f.get("severity") == "error" for f in creport.get("findings", [])):
                    cand_ok = False
                    break
            if cand_ok:
                all_wits = [w for cdoc in cand_wit_docs for w in cdoc["witnesses"]]
                all_calcs = [cw for cdoc in cand_wit_docs for cw in cdoc.get("calc_witnesses", ())]
                verified_complete = (cand_snap_bytes, all_wits, all_calcs)
                break
        if verified_complete is None:
            checker_valid = False
        else:
            complete_snap_bytes, complete_wits, complete_calcs = verified_complete
            claimed_full = frozenset(snap["relation"] for snap in role_snaps if snap.get("full") is True)
            role_manifest = {**manifest, "snapshots": [{**snap, "complete": True} for snap in role_snaps]}
            for proof_doc in role_witness_docs:
                calc_witnesses = proof_doc.get("calc_witnesses", ())
                try:
                    verified_full, role_findings = checker_access.check_role(
                        role_name,
                        complete_snap_bytes,
                        role_snap_bytes,
                        claimed_full,
                        bundle_doc,
                        rules_doc,
                        calc_doc,
                        complete_wits,
                        complete_calcs,
                        calc_witnesses,
                        proof_doc["witnesses"],
                    )
                except (KeyError, TypeError, ValueError):
                    checker_valid = False
                    break
                if any(f.get("severity", "error") == "error" for f in role_findings):
                    checker_valid = False
                    break
                try:
                    report = rezono_checker.check_epoch(
                        proof_doc["witnesses"],
                        role_manifest,
                        rules_obj,
                        archive_reader,
                        derived=derived,
                        full=verified_full,
                        seals=(),
                        calc_witnesses=calc_witnesses,
                        calc_ir=calc_doc,
                    )
                except (KeyError, TypeError, ValueError):
                    checker_valid = False
                    break
                if not report.get("valid") or any(f.get("severity") == "error" for f in report.get("findings", [])):
                    checker_valid = False
                    break
    else:
        checker_valid = False

_assert_all_rezono_modules_pinned()

rows: dict[str, list[dict]] = {}
if checker_valid and role_snap_bytes is not None:
    try:
        for rel, raw in role_snap_bytes.items():
            decoded = json.loads(raw)
            if not isinstance(decoded, list):
                checker_valid = False
                rows = {}
                break
            rows[rel] = decoded
    except (ValueError, json.JSONDecodeError):
        checker_valid = False
        rows = {}

result_path.write_text(
    json.dumps(
        {
            "valid": checker_valid,
            "manifest": manifest if checker_valid else None,
            "rows": rows if checker_valid else {},
        },
        sort_keys=True,
    ),
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


def _scrubbed_env() -> dict[str, str]:
    """Return a minimal subprocess environment stripped of Python/pytest override variables."""
    return {
        key: value
        for key, value in os.environ.items()
        if key in _SAFE_SUBPROCESS_ENV_KEYS
    }


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
    missing = [rel for rel in _REQUIRED_PINNED_PATHS if rel not in available]
    if missing:
        raise ValueError(
            f"pinned commit {engine_sha} is missing required engine/pack paths: {', '.join(missing)}"
        )
    archive_bytes = _git(root, "archive", engine_sha, "--", *available)
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
        tar.extractall(target_dir, filter="data")
    if not (target_dir / BUILD_PACK_MANIFEST).is_file():
        raise ValueError(f"pinned commit {engine_sha} is missing {BUILD_PACK_MANIFEST}")
    _write_pinned_metadata(target_dir)


_ALLOWED_BUILD_EVENTS = frozenset({
    "pull_request",
    "merge_group",
    "push",
    "schedule",
    "workflow_dispatch",
})
_PKG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _format_utc(timestamp: int) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_event_time(value: int | str | None) -> int:
    """Parse an explicit source event timestamp (Unix seconds or ISO-8601 UTC string)."""
    if isinstance(value, bool) or value is None:
        raise ValueError("explicit event_time is required")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"event_time must be non-negative, got {value!r}")
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("explicit event_time is required")
        if stripped.isdigit():
            return int(stripped)
        iso = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
        parsed = dt.datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            raise ValueError(f"ISO event_time must include timezone offset or 'Z', got {value!r}")
        ts = int(parsed.timestamp())
        if ts < 0:
            raise ValueError(f"event_time must be non-negative, got {value!r}")
        return ts
    raise ValueError(f"event_time must be an integer Unix timestamp or ISO-8601 UTC string, got {value!r}")


def _resolve_engine_sha(*, root: Path, pin_path: Path | None) -> str:
    """Resolve the pinned engine SHA strictly from ``build/engine-pin.yaml`` (or explicit pin file)."""
    resolved_pin = pin_path if pin_path is not None else root / ENGINE_PIN_REL
    return read_engine_pin(resolved_pin)


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
    engine_sha: str | None = None
    try:
        engine_sha = _resolve_engine_sha(root=root, pin_path=pin_path)
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
                payload["evidence_dir"] = str(evidence_dir.resolve())
            payload_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-E",
                    "-P",
                    "-c",
                    _PINNED_WORKER_SCRIPT,
                    str(pinned_root),
                    str(root.resolve()),
                    str(payload_path),
                    str(result_path),
                ],
                cwd=pinned_root,
                env=_scrubbed_env(),
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


def _verify_publication_on_pinned_engine(
    *,
    root: Path,
    manifest_path: Path,
    archive_dir: Path,
    role: str,
    role_mode: str,
    pin_path: Path | None = None,
    candidate_sha: str | None = None,
    main_ref: str = DEFAULT_MAIN_REF,
    evidence_dir: Path | None = None,
    timeout_seconds: int = PINNED_TIMEOUT_SECONDS,
) -> tuple[bool, dict[str, Any] | None, dict[str, list[dict[str, Any]]] | None, str | None]:
    """Verify an existing archive publication via ``rezono_checker`` from the pinned engine.

    Returns ``(checker_valid, verified_manifest, rows, engine_error)`` from the same atomic
    verification pass to avoid manifest/rows TOCTOU drift. Any pin or pinned subprocess failure
    returns ``(False, None, None, engine_error)``; any rejected publication returns
    ``(False, None, {}, None)``.
    """
    try:
        engine_sha = _resolve_engine_sha(root=root, pin_path=pin_path)
        candidate = candidate_sha or _git_text(root, "rev-parse", "HEAD")
        validate_engine_pin(
            root=root,
            engine_sha=engine_sha,
            candidate_sha=candidate,
            main_ref=main_ref,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return False, None, None, f"engine pin validation failed: {exc}"

    try:
        with tempfile.TemporaryDirectory(prefix="rezono-pinned-verify-") as tmp:
            work = Path(tmp)
            pinned_root = work / "engine"
            pinned_root.mkdir()
            _extract_pinned_engine(root, engine_sha, pinned_root)

            payload_path = work / "payload.json"
            result_path = work / "result.json"
            payload: dict[str, Any] = {
                "manifest_path": str(manifest_path.resolve()),
                "archive_dir": str(archive_dir.resolve()),
                "role": role,
                "role_mode": role_mode,
            }
            if evidence_dir is not None:
                payload["evidence_dir"] = str(evidence_dir.resolve())
            payload_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    "-E",
                    "-P",
                    "-c",
                    _PINNED_VERIFY_SCRIPT,
                    str(pinned_root),
                    str(root.resolve()),
                    str(payload_path),
                    str(result_path),
                ],
                cwd=pinned_root,
                env=_scrubbed_env(),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            if proc.returncode != 0 or not result_path.is_file():
                detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
                first_line = detail.splitlines()[-1] if detail else f"exit {proc.returncode}"
                return False, None, None, f"pinned publication verification failed: {first_line}"

            output = json.loads(result_path.read_text(encoding="utf-8"))
            valid = output.get("valid") is True
            verified_manifest = output.get("manifest")
            rows = output.get("rows")
            if not isinstance(rows, dict):
                return False, None, None, "pinned verifier returned malformed payload"
            if valid and not isinstance(verified_manifest, dict):
                return False, None, None, "pinned verifier returned malformed manifest payload"
            return valid, verified_manifest if valid else None, rows if valid else {}, None
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError, json.JSONDecodeError) as exc:
        return False, None, None, f"pinned publication verification failed: {exc}"


def _resolve_git_range(
    root: Path,
    *,
    event_name: str,
    base_ref: str,
    before_sha: str,
    merge_group_base: str,
    merge_group_head: str,
) -> tuple[str, str, str, list[str]]:
    """Return ``(build_event, base_sha, head_sha, changed_paths)`` without fabricating ranges or event kinds."""
    head_sha = _git_text(root, "rev-parse", "HEAD")
    if not _SHA40.fullmatch(head_sha):
        raise ValueError(f"HEAD is not a 40-hex commit SHA: {head_sha!r}")

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
    elif event_name == "pull_request":
        if not isinstance(base_ref, str) or not base_ref.strip():
            raise ValueError("pull_request event requires non-empty base_ref")
        bases = _git_text(root, "merge-base", "--all", f"origin/{base_ref}", head_sha).split()
        if len(bases) != 1 or not _SHA40.fullmatch(bases[0]):
            raise ValueError(f"ambiguous merge-base for pull request against origin/{base_ref}")
        base_sha = bases[0]
        build_event = "pull_request"
    elif event_name in ("push", "schedule", "workflow_dispatch"):
        if not (_SHA40.fullmatch(before_sha) and before_sha != _ZERO_SHA):
            raise ValueError(
                f"{event_name} event requires a valid non-zero 40-hex before_sha, got {before_sha!r}"
            )
        subprocess.run(
            ["git", "rev-parse", "--verify", f"{before_sha}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        base_sha = before_sha
        build_event = event_name
    else:
        raise ValueError(f"unsupported or missing event_name: {event_name!r}")

    raw_paths = _git(root, "diff", "--no-renames", "--name-only", "-z", base_sha, head_sha, "--")
    changed_paths = [os.fsdecode(item) for item in raw_paths.split(b"\0") if item]
    return build_event, base_sha, head_sha, changed_paths


def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _regular_git_blob(root: Path, revision: str, rel_path: str) -> tuple[str, bytes] | None:
    """Return ``(blob_sha, raw_bytes)`` if ``rel_path`` is a regular file blob at ``revision``."""
    probe = subprocess.run(
        ["git", "ls-tree", "-z", revision, "--", rel_path],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0 or not probe.stdout:
        return None
    entry = probe.stdout.split(b"\0", 1)[0]
    if b"\t" not in entry:
        return None
    meta = entry.split(b"\t", 1)[0].decode("utf-8", errors="strict").split()
    if len(meta) != 3 or meta[1] != "blob" or meta[0] not in ("100644", "100755"):
        return None
    blob_sha = meta[2]
    if not _SHA40.fullmatch(blob_sha):
        return None
    raw = _git(root, "cat-file", "blob", blob_sha)
    return blob_sha, raw


def _capture_endpoint_manifests(
    root: Path,
    *,
    base_sha: str,
    head_sha: str,
    components: Sequence[Component],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read regular manifest blobs from ``base_sha`` and ``head_sha`` and record declared local dependencies."""
    manifests: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    known_folders = {comp.folder for comp in components}

    for end_label, revision in (("base", base_sha), ("head", head_sha)):
        py_pkg_to_folder: dict[str, str] = {}
        node_pkg_to_folder: dict[str, str] = {}
        endpoint_entries: list[tuple[str, Component, str, str, dict[str, Any]]] = []

        for comp in components:
            py_rel = f"{comp.folder}/pyproject.toml"
            py_blob = _regular_git_blob(root, revision, py_rel)
            if py_blob is not None:
                blob_sha, raw = py_blob
                manifest_id = f"{end_label}-{comp.folder}"
                manifests.append({
                    "id": manifest_id,
                    "component": comp.folder,
                    "path": py_rel,
                    "revision": revision,
                    "blob": blob_sha,
                })
                try:
                    doc = tomllib.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, tomllib.TOMLDecodeError):
                    doc = {}
                project = doc.get("project") if isinstance(doc, dict) else None
                if isinstance(project, dict):
                    pkg_name = project.get("name")
                    if isinstance(pkg_name, str) and pkg_name:
                        py_pkg_to_folder[_normalize_pkg_name(pkg_name)] = comp.folder
                    endpoint_entries.append(("python", comp, manifest_id, py_rel, project))

            node_rel = f"{comp.folder}/package.json"
            node_blob = _regular_git_blob(root, revision, node_rel)
            if node_blob is not None:
                blob_sha, raw = node_blob
                manifest_id = f"{end_label}-{comp.folder}-node" if py_blob is not None else f"{end_label}-{comp.folder}"
                manifests.append({
                    "id": manifest_id,
                    "component": comp.folder,
                    "path": node_rel,
                    "revision": revision,
                    "blob": blob_sha,
                })
                try:
                    doc = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    doc = {}
                if isinstance(doc, dict):
                    pkg_name = doc.get("name")
                    if isinstance(pkg_name, str) and pkg_name:
                        node_pkg_to_folder[pkg_name] = comp.folder
                    endpoint_entries.append(("node", comp, manifest_id, node_rel, doc))

        seen_edges: set[tuple[str, str, str]] = set()
        for kind, comp, manifest_id, rel, doc in endpoint_entries:
            dep_folders: set[str] = set()
            if kind == "python":
                raw_reqs: list[object] = []
                if isinstance(doc.get("dependencies"), list):
                    raw_reqs.extend(doc["dependencies"])
                opt = doc.get("optional-dependencies")
                if isinstance(opt, dict):
                    for items in opt.values():
                        if isinstance(items, list):
                            raw_reqs.extend(items)
                for req in raw_reqs:
                    if not isinstance(req, str):
                        continue
                    match = _PKG_NAME_RE.match(req.strip())
                    if not match:
                        continue
                    target = py_pkg_to_folder.get(_normalize_pkg_name(match.group(0)))
                    if target and target != comp.folder and target in known_folders:
                        dep_folders.add(target)
            else:
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    mapping = doc.get(section)
                    if not isinstance(mapping, dict):
                        continue
                    for dep_name in mapping:
                        if not isinstance(dep_name, str):
                            continue
                        target = node_pkg_to_folder.get(dep_name)
                        if target and target != comp.folder and target in known_folders:
                            dep_folders.add(target)

            for dep_folder in sorted(dep_folders):
                key = (manifest_id, dep_folder, comp.folder)
                if key in seen_edges:
                    continue
                seen_edges.add(key)
                dependencies.append({
                    "id": f"dep-{manifest_id}-{dep_folder}-to-{comp.folder}",
                    "dependency": dep_folder,
                    "consumer": comp.folder,
                    "kind": "manifest",
                    "manifest": manifest_id,
                    "source": rel,
                })

    return manifests, dependencies


def _read_submitted_receipt_id(evidence_dir: Path | None) -> str | None:
    """Read a unique submitted completeness receipt ID from ``evidence_dir``, if present and digest-valid."""
    if evidence_dir is None:
        return None
    root_dir = evidence_dir.resolve()
    archive_root = (root_dir / "archive").resolve()
    index_file = root_dir / "index.json"
    if not index_file.is_file():
        index_file = archive_root / "observations" / "submitted" / "index.json"
    if not index_file.is_file():
        return None
    try:
        index_doc = json.loads(index_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(index_doc, dict):
        return None
    receipts = index_doc.get("completeness_receipts")
    if not isinstance(receipts, list) or len(receipts) != 1:
        return None
    ref = receipts[0]
    if not isinstance(ref, dict):
        return None
    expected_sha = ref.get("sha256")
    if not isinstance(expected_sha, str) or not _SHA64.fullmatch(expected_sha):
        return None
    blob_path = _resolve_archive_blob(archive_root, ref.get("uri") or ref.get("file"))
    if blob_path is None:
        return None
    try:
        raw = blob_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha:
            return None
        receipt_doc = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    receipt_id = receipt_doc.get("id") if isinstance(receipt_doc, dict) else None
    return receipt_id if isinstance(receipt_id, str) and receipt_id else None


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
    evidence_dir: Path | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build typed ``build/`` observation records and honest ``tool`` provenance sidecar."""
    if build_event not in _ALLOWED_BUILD_EVENTS:
        raise ValueError(f"unsupported build_event: {build_event!r}")
    if isinstance(observed_at, bool) or not isinstance(observed_at, int) or observed_at < 0:
        raise ValueError(f"observed_at must be a non-negative integer timestamp, got {observed_at!r}")

    sorted_by_specificity = sorted(components, key=lambda c: (-len(c.folder), c.folder))
    build_paths: list[dict[str, Any]] = []
    build_path_readers: list[dict[str, Any]] = []
    for idx, raw_path in enumerate(changed_paths, start=1):
        path_id = f"path-{idx}"
        owner = next(
            (comp for comp in sorted_by_specificity if raw_path == comp.folder or raw_path.startswith(comp.folder + "/")),
            None,
        )
        if owner is not None:
            build_paths.append({"id": path_id, "run": run_id, "path": raw_path, "coverage": "mapped"})
            build_path_readers.append({
                "id": f"reader-{path_id}-{owner.folder}",
                "path": path_id,
                "component": owner.folder,
                "kind": "transitive",
                "source": owner.folder,
            })
        else:
            build_paths.append({"id": path_id, "run": run_id, "path": raw_path, "coverage": "unknown"})

    build_manifests, build_dependencies = _capture_endpoint_manifests(
        root,
        base_sha=base_sha,
        head_sha=head_sha,
        components=components,
    )

    build_run_row: dict[str, Any] = {
        "id": run_id,
        "event": build_event,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "engine_sha": engine_sha,
        "observed_at": observed_at,
    }
    receipt_id = _read_submitted_receipt_id(evidence_dir)
    if receipt_id is not None:
        build_run_row["receipt"] = receipt_id

    records: dict[str, list[dict[str, Any]]] = {
        "build_run": [build_run_row],
        "build_component": [
            {"id": comp.folder, "run": run_id, "kind": comp.kind, "folder": comp.folder}
            for comp in components
        ],
        "build_test_file": [
            {"id": f"tf-{comp.folder}-{idx}", "component": comp.folder, "path": rel}
            for comp in components
            for idx, rel in enumerate(_test_files(root, comp.folder), start=1)
        ],
        "build_path": build_paths,
    }
    if build_path_readers:
        records["build_path_reader"] = build_path_readers
    if build_manifests:
        records["build_manifest"] = build_manifests
    if build_dependencies:
        records["build_dependency"] = build_dependencies
    if receipt_id is not None:
        records["loop_sweep_receipt"] = [{"id": receipt_id, "run": run_id, "event_time": observed_at}]

    sources_sidecar = {
        "default": {
            "kind": "tool",
            "name": "loop/ci_discover.py",
            "revision": head_sha,
            "position": f"ci-observe:{repository_name}:{base_sha}..{head_sha}",
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
    event_time: int | str | None = None,
    pin_path: Path | None = None,
    main_ref: str = DEFAULT_MAIN_REF,
    records_override: Mapping[str, Any] | None = None,
    sources_sidecar_override: Mapping[str, Any] | None = None,
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

    try:
        engine_sha = _resolve_engine_sha(root=root, pin_path=pin_path)
        if records_override is not None:
            head_sha = _git_text(root, "rev-parse", "HEAD")
            if event_time is not None:
                observed_at = _parse_event_time(event_time)
            else:
                runs = records_override.get("build_run")
                if not isinstance(runs, list) or not runs or not isinstance(runs[0], Mapping):
                    raise ValueError("explicit event_time or records_override.build_run[0].observed_at is required")
                observed_at = _parse_event_time(runs[0].get("observed_at"))
            records: Mapping[str, Any] = records_override
            sources_sidecar: Mapping[str, Any] | None = sources_sidecar_override
        else:
            observed_at = _parse_event_time(event_time)
            build_event, base_sha, head_sha, changed_paths = _resolve_git_range(
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
                evidence_dir=evidence_dir,
            )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        engine_error = f"observation capture failed: {exc}"
    else:
        engine_sha, manifest, rows, engine_error = run_pinned_build_pack(
            root=root,
            records=records,
            sources_sidecar=sources_sidecar,
            knowledge_time=_format_utc(observed_at),
            pin_path=pin_path,
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


def _resolve_archive_blob(root_dir: Path, uri: object) -> Path | None:
    """Resolve an archive URI strictly inside ``root_dir``, or return None if invalid."""
    if not isinstance(uri, str) or not uri:
        return None
    if "://" in uri:
        rest = uri.split("://", 1)[1]
        if "/" not in rest:
            return None
        rel = rest.split("/", 1)[1]
    else:
        rel = uri
    if not rel or rel.startswith("/") or "\\" in rel or ".." in Path(rel).parts:
        return None
    blob_path = (root_dir / rel).resolve()
    if not blob_path.is_relative_to(root_dir) or not blob_path.is_file():
        return None
    return blob_path


def _rejected_manifest(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Mark a publication manifest rejected so downstream readers enter ``invalid-publication`` safe mode."""
    base = dict(manifest) if isinstance(manifest, Mapping) else {}
    existing = [dict(c) for c in base.get("checks", []) if isinstance(c, Mapping)]
    existing.append({"name": "rezono:proofs", "status": "red", "violations": 1})
    return {**base, "checks": existing}


def _load_publication_files(
    *,
    manifest_path: Path | None,
    rows_path: Path | None,
    archive_dir: Path | None,
    role: str,
) -> tuple[dict[str, Any] | None, dict[str, list[dict[str, Any]]] | None, str | None]:
    """Read a published manifest and digest-verified archive snapshots & witnesses, failing closed.

    Unverified raw ``--rows`` files are never trusted: they fail closed into ``invalid-publication``
    safe mode. Archive publications require at least one snapshot and at least one digest-verified
    witness entry for ``role`` before independent verification via ``rezono_checker``.
    """
    if manifest_path is None:
        return None, None, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return _rejected_manifest(None), {}, None
        if rows_path is not None:
            # Never trust raw unverified --rows JSON without archive digests, witnesses, and rezono_checker.
            return _rejected_manifest(manifest), {}, None
        if archive_dir is None:
            return manifest, None, None

        if not isinstance(manifest.get("id"), str) or not manifest["id"]:
            return _rejected_manifest(manifest), {}, None

        snapshots = manifest.get("snapshots")
        if not isinstance(snapshots, list):
            return _rejected_manifest(manifest), {}, None

        root_dir = archive_dir.resolve()
        rows: dict[str, list[dict[str, Any]]] = {}
        for entry in snapshots:
            if not isinstance(entry, dict):
                return _rejected_manifest(manifest), {}, None
            if entry.get("role") != role:
                continue
            relation = entry.get("relation")
            expected_sha = entry.get("sha256")
            if not isinstance(relation, str) or not relation or relation in rows:
                return _rejected_manifest(manifest), {}, None
            if not isinstance(expected_sha, str) or not _SHA64.fullmatch(expected_sha):
                return _rejected_manifest(manifest), {}, None
            if entry.get("format") != "json":
                return _rejected_manifest(manifest), {}, None
            blob_path = _resolve_archive_blob(root_dir, entry.get("uri"))
            if blob_path is None:
                return _rejected_manifest(manifest), {}, None
            raw = blob_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                return _rejected_manifest(manifest), {}, None
            decoded = json.loads(raw)
            if not isinstance(decoded, list):
                return _rejected_manifest(manifest), {}, None
            rows[relation] = decoded

        if not rows:
            return _rejected_manifest(manifest), {}, None

        witnesses = manifest.get("witnesses")
        if not isinstance(witnesses, list):
            return _rejected_manifest(manifest), {}, None

        role_witness_count = 0
        for entry in witnesses:
            if not isinstance(entry, dict):
                return _rejected_manifest(manifest), {}, None
            if entry.get("role") != role:
                continue
            expected_sha = entry.get("sha256")
            if not isinstance(expected_sha, str) or not _SHA64.fullmatch(expected_sha):
                return _rejected_manifest(manifest), {}, None
            blob_path = _resolve_archive_blob(root_dir, entry.get("uri"))
            if blob_path is None:
                return _rejected_manifest(manifest), {}, None
            raw = blob_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                return _rejected_manifest(manifest), {}, None
            proof_doc = json.loads(raw)
            if not isinstance(proof_doc, dict) or not isinstance(proof_doc.get("witnesses"), list):
                return _rejected_manifest(manifest), {}, None
            role_witness_count += 1

        if role_witness_count == 0:
            return _rejected_manifest(manifest), {}, None

        return manifest, rows, None
    except (OSError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
        return _rejected_manifest(None), {}, None


def _load_optional_sources_sidecar(
    records_path: Path,
    sources_path: Path | None,
) -> Mapping[str, Any] | None:
    """Load an explicit or sibling ``.sources.yaml`` sidecar without fabricating provenance."""
    candidate = sources_path
    if candidate is None:
        sibling = records_path.with_suffix(".sources.yaml")
        if sibling.is_file():
            candidate = sibling
    if candidate is None:
        return None
    loaded = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"sources sidecar {candidate} must contain a YAML mapping")
    return loaded


def evaluate_coordinator_state(
    *,
    root: Path = ROOT,
    run_id: str = DEFAULT_RUN_ID,
    manifest_path: Path | None = None,
    rows_path: Path | None = None,
    archive_dir: Path | None = None,
    records_path: Path | None = None,
    sources_path: Path | None = None,
    pin_path: Path | None = None,
    main_ref: str = DEFAULT_MAIN_REF,
    role: str = "reader",
    role_mode: str = "complete",
    knowledge_time: str | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    """Read coordinator task and claim-release state from a checker-verified build publication."""
    manifest: dict[str, Any] | None = None
    rows: dict[str, list[dict[str, Any]]] | None = None
    engine_error: str | None = None

    if records_path is not None:
        if not isinstance(knowledge_time, str) or not knowledge_time.strip():
            raise ValueError("explicit knowledge_time is required when evaluating coordinator records")
        try:
            records = yaml.safe_load(records_path.read_text(encoding="utf-8"))
            if not isinstance(records, Mapping):
                raise ValueError(f"records file {records_path} must contain a mapping")
            sources_sidecar = _load_optional_sources_sidecar(records_path, sources_path)
            head_sha = _git_text(root, "rev-parse", "HEAD")
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
        if engine_error is None and archive_dir is not None and rows_path is None and rows:
            checker_valid, verified_manifest, verified_rows, verify_error = _verify_publication_on_pinned_engine(
                root=root,
                manifest_path=manifest_path,
                archive_dir=archive_dir,
                role=role,
                role_mode=role_mode,
                pin_path=pin_path,
                main_ref=main_ref,
                evidence_dir=evidence_dir,
            )
            if verify_error is not None:
                manifest = None
                rows = None
                engine_error = verify_error
            elif not checker_valid or verified_manifest is None or verified_rows is None:
                manifest = _rejected_manifest(manifest)
                rows = {}
            else:
                manifest = verified_manifest
                rows = verified_rows

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
    matrix_p.add_argument("--pin", "--pin-file", dest="pin", type=Path, default=None)
    matrix_p.add_argument("--main-ref", default=DEFAULT_MAIN_REF)
    matrix_p.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    matrix_p.add_argument("--base-ref", default=os.environ.get("GITHUB_BASE_REF", ""))
    matrix_p.add_argument("--before", default=os.environ.get("GITHUB_EVENT_BEFORE", ""))
    matrix_p.add_argument("--merge-group-base", default=os.environ.get("MERGE_GROUP_BASE_SHA", ""))
    matrix_p.add_argument("--merge-group-head", default=os.environ.get("MERGE_GROUP_HEAD_SHA", ""))
    matrix_p.add_argument("--event-time", default=os.environ.get("GITHUB_EVENT_TIME", ""))
    matrix_p.add_argument("--evidence-dir", type=Path, default=None)
    matrix_p.add_argument("--json", dest="as_json", action="store_true")

    coord_p = sub.add_parser("coordinator-state", help="Read coordinator state from verified build/ publication.")
    coord_p.add_argument("--root", type=Path, default=None)
    coord_p.add_argument("--run", dest="run_id", default=DEFAULT_RUN_ID)
    coord_p.add_argument("--manifest", type=Path, default=None)
    coord_p.add_argument("--rows", type=Path, default=None)
    coord_p.add_argument("--archive", type=Path, default=None)
    coord_p.add_argument("--records", type=Path, default=None)
    coord_p.add_argument("--sources", type=Path, default=None)
    coord_p.add_argument("--pin", "--pin-file", dest="pin", type=Path, default=None)
    coord_p.add_argument("--main-ref", default=DEFAULT_MAIN_REF)
    coord_p.add_argument("--role", default="reader")
    coord_p.add_argument("--role-mode", default="complete")
    coord_p.add_argument("--knowledge-time", default=None)
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
            event_time=args.event_time or None,
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
        if args.records is not None and not (isinstance(args.knowledge_time, str) and args.knowledge_time.strip()):
            parser.error("--knowledge-time is required when --records is provided")
        state = evaluate_coordinator_state(
            root=resolved_root,
            run_id=args.run_id,
            manifest_path=args.manifest,
            rows_path=args.rows,
            archive_dir=args.archive,
            records_path=args.records,
            sources_path=args.sources,
            pin_path=args.pin,
            main_ref=args.main_ref,
            role=args.role,
            role_mode=args.role_mode,
            knowledge_time=args.knowledge_time,
            evidence_dir=args.evidence_dir,
        )
        print(json.dumps(state, indent=2, sort_keys=True))
        if args.fail_on_safe_mode and state.get("safe_mode"):
            return 2
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
