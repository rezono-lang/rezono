"""Strict red tests for the quality and contract defects in ``loop/ci_discover.py``.

Covers five contracts from ``decisions/build-reconciliation.md`` and
``decisions/tooling-does-not-decide.md``:

1. ``rezono:schema`` is emitted by ``rezono_publisher`` / ``rezono_checker`` (with contract
   documentation), never synthesized by ``loop/ci_discover.py``.
2. CI shard counts come from pack facts in ``build/`` through one shared matrix renderer
   (``loop.build_job_matrix``), with no copied shard tables or selection logic from
   ``scripts/components.py``.
3. Honest CI observation capture: distinct event kinds (``push``, ``schedule``,
   ``workflow_dispatch``) are preserved instead of rewritten to ``merge_group``; missing
   ``--before`` fails closed instead of falling back to ``HEAD`` (empty diff); changed paths
   receive real path/manifest coverage rather than hardcoded ``"unknown"``; recorded time is
   the source event time rather than the Git commit timestamp.
4. No hardcoded test date ``"2027-01-15T08:00:00Z"`` in production defaults, and no
   ``--pin-sha`` CLI override bypassing ``build/engine-pin.yaml``.
5. End-to-end behavioral verification of ``loop/ci_discover.py`` (``ci-matrix`` and
   ``coordinator-state``) against independent, hand-written records for happy path,
   fail-closed ``safe_mode``, and role-scoped publication.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_DISCOVER = ROOT / "loop" / "ci_discover.py"
BUILD_DIR = ROOT / "build"
MANIFEST_CONTRACT = ROOT / "contracts" / "manifest.yaml"

COMMIT_TIME = 1_700_000_000  # 2023-11-14T22:13:20Z (deliberately far from EVENT_TIME)
EVENT_TIME = 1_810_000_200   # 2027-05-11T01:50:00Z (distinct from COMMIT_TIME and 2027-01-15)
EVENT_ISO = "2027-05-11T01:50:00Z"
EVENT_DAY_STR = "2027-05-11"
EVENT_DAY_INT = 20270511
LEASE_SECONDS = 4 * 60 * 60
SUITES = ("alpha", "beta", "gamma", "spare")
AUTHORITY_PATH = "observer/build-readers.json"

_ENGINE_DIRS = (
    "build",
    "compiler",
    "edge/publisher",
    "checker",
    "canon",
    "admission",
    "contracts",
    "packs",
    "publication",
    "rezono",
)
_COPY_SKIP = frozenset({"__pycache__", "tests", "fixtures", ".pytest_cache", "node_modules"})


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Build Test",
            "-c",
            "user.email=build-test@example.org",
            *args,
        ],
        cwd=root,
        env=merged,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def _commit_env(epoch_seconds: int = COMMIT_TIME) -> dict[str, str]:
    stamp = f"{epoch_seconds} +0000"
    return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                ids.add(id(node.body[0].value))
    return ids


def _code_string_literals(tree: ast.AST) -> set[str]:
    doc_ids = _docstring_nodes(tree)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in doc_ids
    }


def _embedded_python_trees(tree: ast.AST) -> list[ast.Module]:
    embedded: list[ast.Module] = []
    for literal in _code_string_literals(tree):
        if "\n" not in literal or not ("import " in literal or "def " in literal):
            continue
        try:
            parsed = ast.parse(literal)
        except SyntaxError:
            continue
        if len(parsed.body) >= 2:
            embedded.append(parsed)
    return embedded


def _all_ci_discover_code_literals() -> set[str]:
    tree = ast.parse(CI_DISCOVER.read_text(encoding="utf-8"), filename=str(CI_DISCOVER))
    literals = _code_string_literals(tree)
    for sub_tree in _embedded_python_trees(tree):
        literals.update(_code_string_literals(sub_tree))
    return literals


def _copy_engine_tree(dst: Path) -> None:
    def _ignore(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name in _COPY_SKIP]

    for rel in _ENGINE_DIRS:
        src = ROOT / rel
        if src.is_dir():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, target, ignore=_ignore)


def _create_synthetic_components(repo: Path) -> None:
    deps = {"alpha": [], "beta": ["alpha"], "gamma": ["beta"], "spare": []}
    for name in SUITES:
        comp_dir = repo / name
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "pyproject.toml").write_text(
            f"[project]\nname = {json.dumps(name)}\nversion = \"0.1.0\"\n"
            f"dependencies = {json.dumps(deps[name])}\n",
            encoding="utf-8",
        )
        (comp_dir / "test_unit.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _make_isolated_pinned_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Create a hermetic 3-commit Git repo:

    - Commit 1 (``engine_sha``): pinned engine & pack snapshot (ancestor of ``origin/main``).
    - Commit 2 (``base_sha`` / ``refs/remotes/origin/main``): clean synthetic candidate repo
      containing ``build/engine-pin.yaml`` (pointing to Commit 1) and the four synthetic suites
      (``alpha``, ``beta``, ``gamma``, ``spare``).
    - Commit 3 (``head_sha`` / ``HEAD``): candidate change touching only ``alpha/engine.py``.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _copy_engine_tree(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Seed pinned engine snapshot", env=_commit_env(COMMIT_TIME))
    engine_sha = _git(repo, "rev-parse", "HEAD")

    for child in list(repo.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    (repo / "build").mkdir()
    (repo / "build" / "engine-pin.yaml").write_text(f"engine_sha: {engine_sha}\n", encoding="utf-8")
    _create_synthetic_components(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "Seed synthetic candidate repository", env=_commit_env(COMMIT_TIME))
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    (repo / "alpha" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Candidate change in alpha", env=_commit_env(COMMIT_TIME))
    head_sha = _git(repo, "rev-parse", "HEAD")
    return repo, engine_sha, base_sha, head_sha


def _archived_ref(key: str, value: Any) -> dict[str, str]:
    from rezono_canon import canonical_sha256

    return {"file": key, "uri": f"s3://rezono/{key}", "sha256": canonical_sha256(value)}


def _build_selection_records_and_evidence(
    repo: Path,
    *,
    base_sha: str,
    head_sha: str,
    engine_sha: str,
    run_id: str,
    observed_at: int,
    evidence_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hand-write independent build-selection records and admitted completeness evidence for alpha/engine.py."""
    from rezono_canon import canonical_bytes, canonical_sha256

    changed_path = "alpha/engine.py"
    registry = {
        "paths": {changed_path: {"direct": [], "transitive": ["alpha"]}},
        "file_dependencies": [],
    }
    contents: list[dict[str, Any]] = []

    def add_member(key: list[str], origin: dict[str, Any], rows: list[Any]) -> None:
        terminal = {
            "kind": "git",
            "name": "hand-written-observer",
            "revision": origin.get("revision", head_sha),
            "position": origin.get("path", f"{base_sha}..{head_sha}"),
        }
        contents.append({
            "key": key,
            "terminal": terminal,
            "rows": [
                {"key": [*key, idx], "values": {"value": val, **origin}, "source": terminal}
                for idx, val in enumerate(rows)
            ],
        })

    add_member(["changed-path", changed_path], {"base": base_sha, "head": head_sha}, [changed_path])
    add_member(["path-readers", changed_path, "direct"], {"revision": engine_sha, "path": AUTHORITY_PATH}, [])
    add_member(
        ["path-readers", changed_path, "transitive"],
        {"revision": engine_sha, "path": AUTHORITY_PATH},
        ["alpha"],
    )
    add_member(
        ["path-reader", changed_path, "transitive", "alpha"],
        {"revision": engine_sha, "path": AUTHORITY_PATH},
        ["alpha"],
    )
    add_member(["file-dependencies"], {"revision": engine_sha, "path": AUTHORITY_PATH}, [])

    for revision in (base_sha, head_sha):
        for suite in SUITES:
            manifest_rel = f"{suite}/pyproject.toml"
            blob = _git(repo, "rev-parse", f"{revision}:{manifest_rel}")
            project = tomllib.loads(_git(repo, "show", f"{revision}:{manifest_rel}"))["project"]
            origin = {"revision": revision, "path": manifest_rel, "mode": "100644", "blob": blob}
            add_member(["manifest", revision, manifest_rel], origin, [project])
            deps = project.get("dependencies", [])
            add_member(["manifest-dependencies", revision, manifest_rel], origin, deps)
            for dep in deps:
                add_member(["manifest-dependency", revision, manifest_rel, dep], origin, [dep])
        if revision == head_sha:
            for suite in SUITES:
                test_rel = f"{suite}/test_unit.py"
                blob = _git(repo, "rev-parse", f"{head_sha}:{test_rel}")
                add_member(
                    ["test-file", test_rel],
                    {"revision": head_sha, "path": test_rel, "mode": "100644", "blob": blob},
                    [test_rel],
                )
    for suite in SUITES:
        add_member(["suite", suite], {"revision": head_sha, "path": suite}, ["python"])

    contents.sort(key=lambda item: canonical_bytes(item["key"]))
    inventory = [item["key"] for item in contents]
    authorization = {
        "issuer": "protected-build-observer",
        "source": "hand-written-observer",
        "query": "build-selection",
        "engine_sha": engine_sha,
        "path": AUTHORITY_PATH,
    }
    bindings = [
        {"name": name, "type": "Integer" if isinstance(value, int) else "Text", "value": value}
        for name, value in (
            ("attempt", 1),
            ("base_sha", base_sha),
            ("engine_sha", engine_sha),
            ("event", "pull_request"),
            ("head_sha", head_sha),
            ("observed_at", observed_at),
            ("run", run_id),
        )
    ]
    receipt_body = {
        "source": {
            "kind": "git",
            "name": "hand-written-observer",
            "revision": head_sha,
            "position": f"{base_sha}..{head_sha}",
        },
        "issuer": {
            "id": "protected-build-observer",
            "authorization": _archived_ref("observations/retained/authorization.json", authorization),
        },
        "scope": {
            "definition": _archived_ref("observations/retained/definition.json", registry),
            "query": "build-selection",
            "bindings": bindings,
        },
        "cut": {"frontier": {"source_id": "hand-written-observer", "position": head_sha}},
        "inventory": _archived_ref("observations/submitted/inventory.json", inventory),
        "content": _archived_ref("observations/submitted/content.json", contents),
    }
    receipt_id = canonical_sha256(["rezono.completeness-receipt/1", receipt_body])
    receipt = {"id": receipt_id, **receipt_body}

    archive_objects = {
        "observations/retained/authorization.json": authorization,
        "observations/retained/definition.json": registry,
        "observations/retained/inventory.json": inventory,
        "observations/retained/content.json": contents,
        "observations/submitted/inventory.json": inventory,
        "observations/submitted/content.json": contents,
        "observations/submitted/receipt.json": receipt,
    }
    archive_dir = evidence_dir / "archive"
    for rel, value in archive_objects.items():
        target = archive_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_bytes(value))

    protected_context = {
        "source": receipt["source"],
        "issuer": receipt["issuer"],
        "scope": receipt["scope"],
        "cut": receipt["cut"],
        "inventory": _archived_ref("observations/retained/inventory.json", inventory),
        "content": _archived_ref("observations/retained/content.json", contents),
    }
    context_doc = {"completeness": [protected_context]}
    index_doc = {"completeness_receipts": [_archived_ref("observations/submitted/receipt.json", receipt)]}
    (evidence_dir / "context.json").write_bytes(canonical_bytes(context_doc))
    (evidence_dir / "index.json").write_bytes(canonical_bytes(index_doc))

    records: dict[str, Any] = {
        "build_run": [{
            "id": run_id,
            "event": "pull_request",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "engine_sha": engine_sha,
            "observed_at": observed_at,
            "receipt": receipt_id,
        }],
        "loop_sweep_receipt": [{"id": receipt_id, "run": run_id, "event_time": observed_at}],
        "build_component": [
            {"id": suite, "run": run_id, "kind": "python", "folder": suite} for suite in SUITES
        ],
        "build_manifest": [
            {
                "id": f"{end}-{suite}",
                "component": suite,
                "path": f"{suite}/pyproject.toml",
                "revision": rev,
                "blob": _git(repo, "rev-parse", f"{rev}:{suite}/pyproject.toml"),
            }
            for end, rev in (("base", base_sha), ("head", head_sha))
            for suite in SUITES
        ],
        "build_test_file": [
            {"id": f"{suite}-test", "component": suite, "path": f"{suite}/test_unit.py"} for suite in SUITES
        ],
        "build_dependency": [
            {
                "id": f"{end}-{consumer}-dep",
                "dependency": dep,
                "consumer": consumer,
                "kind": "manifest",
                "manifest": f"{end}-{consumer}",
                "source": f"{consumer}/pyproject.toml",
            }
            for end in ("base", "head")
            for consumer, dep in (("beta", "alpha"), ("gamma", "beta"))
        ],
        "build_path": [
            {"id": "change-1", "run": run_id, "path": changed_path, "coverage": "mapped"}
        ],
        "build_path_reader": [
            {
                "id": "reader-alpha",
                "path": "change-1",
                "component": "alpha",
                "kind": "transitive",
                "source": "alpha",
            }
        ],
    }
    sidecar = {
        "default": {
            "kind": "tool",
            "name": "hand-written-selection",
            "revision": head_sha,
            "position": f"{base_sha}..{head_sha}",
        }
    }
    return records, sidecar


def _claim_generation(label: str) -> str:
    return hashlib.sha1(label.encode("utf-8")).hexdigest()


def _build_coordinator_records(
    *,
    base_sha: str,
    head_sha: str,
    engine_sha: str,
    run_id: str,
    observed_at: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hand-write independent task, claim, and role records for coordinator-state evaluation."""
    exp_gen = _claim_generation("task/expired")
    act_gen = _claim_generation("task/active")
    records: dict[str, Any] = {
        "role": [{"id": "unprivileged", "title": "Unprivileged"}],
        "build_run": [{
            "id": run_id,
            "event": "pull_request",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "engine_sha": engine_sha,
            "observed_at": observed_at,
            "receipt": "rcpt-coord",
        }],
        "loop_sweep_receipt": [{"id": "rcpt-coord", "run": run_id, "event_time": observed_at}],
        "loop_active_run": [{"id": run_id}],
        "loop_step": [
            {"id": "lang"},
            {"id": "core", "precedes": ["wait"]},
            {"id": "wait"},
            {"id": "stuck"},
        ],
        "loop_completion": [{
            "id": "core-evidence",
            "run": run_id,
            "step": "core",
            "token": "compiled-core",
            "reason": "compile-result",
        }],
        "loop_expectation": [{"id": "compiled-core", "value": "passed"}],
        "loop_refusal": [{
            "id": "refuse-stuck",
            "run": run_id,
            "step": "stuck",
            "reason": "terminal-refusal",
        }],
        "build_task": [
            {"id": "task-lang", "run": run_id, "step": "lang", "track": "language", "source": "board"},
            {"id": "task-core", "run": run_id, "step": "core", "track": "core", "source": "board"},
            {"id": "task-wait", "run": run_id, "step": "wait", "track": "language", "source": "board"},
            {"id": "task-stuck", "run": run_id, "step": "stuck", "track": "language", "source": "board"},
        ],
        "reference_date": [{
            "id": "policy-day",
            "title": "Observed reference day",
            "date": EVENT_DAY_STR,
            "day": EVENT_DAY_INT,
        }],
        "build_policy_date": [{
            "id": "policy-cut",
            "run": run_id,
            "reference": "policy-day",
            "observed_at": observed_at,
        }],
        "decision": [{
            "id": "lease-policy",
            "title": "Claim lease duration",
            "state": "in_force",
            "valid_from": "2027-01-01",
            "valid_from_day": 20270101,
            "decider": ["build-policy"],
        }],
        "build_claim_lease": [{
            "id": "lease-4h",
            "decision": "lease-policy",
            "seconds": LEASE_SECONDS,
        }],
        "build_claim": [
            {
                "id": "task/expired",
                "run": run_id,
                "branch": "task/expired",
                "generation": exp_gen,
                "observed_at": observed_at,
                "source": "ref-listing",
            },
            {
                "id": "task/active",
                "run": run_id,
                "branch": "task/active",
                "generation": act_gen,
                "observed_at": observed_at,
                "source": "ref-listing",
            },
        ],
        "build_claim_activity": [
            {
                "id": "push-expired",
                "claim": "task/expired",
                "after": exp_gen,
                "pushed_at": observed_at - LEASE_SECONDS,
                "source": "push-activity",
            },
            {
                "id": "push-active",
                "claim": "task/active",
                "after": act_gen,
                "pushed_at": observed_at - LEASE_SECONDS + 1,
                "source": "push-activity",
            },
        ],
        "build_claim_pull_reading": [
            {
                "id": "pr-expired",
                "claim": "task/expired",
                "observed_at": observed_at,
                "state": "none",
                "source": "pull-query",
                "receipt": "rcpt-coord",
            },
            {
                "id": "pr-active",
                "claim": "task/active",
                "observed_at": observed_at,
                "state": "none",
                "source": "pull-query",
                "receipt": "rcpt-coord",
            },
        ],
    }
    sidecar = {
        "default": {
            "kind": "tool",
            "name": "hand-written-coordinator",
            "revision": head_sha,
            "position": f"coord:{run_id}@{observed_at}",
        }
    }
    return records, sidecar


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: rezono:schema must be emitted by "
           "rezono_publisher/rezono_checker and documented in contracts/manifest.yaml, "
           "never synthesized inside loop/ci_discover.py.",
)
def test_rezono_schema_check_emitted_by_publisher_never_synthesized_by_ci_discover(tmp_path: Path):
    """loop/ci_discover.py never fabricates rezono:schema; rezono_publisher/rezono_checker emits it."""
    # 1. Structural check: loop/ci_discover.py (including its embedded pinned worker script)
    #    must never synthesize or inject a "rezono:schema" check entry.
    synthesizes_schema = "rezono:schema" in _all_ci_discover_code_literals()
    assert not synthesizes_schema, (
        "loop/ci_discover.py must not synthesize or inject 'rezono:schema' into manifest checks; "
        "that check belongs solely to rezono_publisher/rezono_checker"
    )

    # 2. Contract documentation check: contracts/manifest.yaml must specify rezono:schema.
    contract_text = MANIFEST_CONTRACT.read_text(encoding="utf-8")
    assert "rezono:schema" in contract_text, (
        "contracts/manifest.yaml must document the rezono:schema check emitted by publisher/checker"
    )

    # 3. Real publisher + checker behavioral check (independent of loop/ci_discover.py).
    from rezono_publisher import batch, publish, store
    work = tmp_path / "pub"
    build_copy = work / "build"
    shutil.copytree(BUILD_DIR, build_copy)
    for pack_name in ("std-access", "std-decision", "std-loop", "std-order", "std-time"):
        src = ROOT / "packs" / pack_name
        if src.is_dir():
            shutil.copytree(src, work / "packs" / pack_name)

    base_sha, head_sha, engine_sha = "1" * 40, "2" * 40, "3" * 40
    (build_copy / "facts").mkdir(exist_ok=True)
    (build_copy / "facts" / "input.yaml").write_text(
        yaml.safe_dump({
            "build_run": [{
                "id": "r-schema",
                "event": "pull_request",
                "base_sha": base_sha,
                "head_sha": head_sha,
                "engine_sha": engine_sha,
                "observed_at": EVENT_TIME,
                "receipt": "rcpt-schema",
            }],
            "loop_sweep_receipt": [{"id": "rcpt-schema", "run": "r-schema", "event_time": EVENT_TIME}],
        }),
        encoding="utf-8",
    )
    (build_copy / "facts" / "input.sources.yaml").write_text(
        yaml.safe_dump({
            "default": {
                "kind": "tool",
                "name": "schema-check-test",
                "revision": head_sha,
                "position": "r-schema",
            }
        }),
        encoding="utf-8",
    )

    archive = store.FileStore(work / "archive")
    epoch = batch.epoch(
        build_copy,
        epoch=1,
        knowledge_time=EVENT_ISO,
        sources=[("facts", "input")],
    )
    manifest = publish.publish(epoch, archive, {"reader": "complete"})
    checks_by_name = {c["name"]: c for c in manifest.get("checks", []) if isinstance(c, dict)}

    assert checks_by_name.get("rezono:proofs") == {
        "name": "rezono:proofs",
        "status": "green",
        "violations": 0,
    }, f"expected green rezono:proofs check from rezono_publisher, got {manifest.get('checks')}"
    assert checks_by_name.get("rezono:schema") == {
        "name": "rezono:schema",
        "status": "green",
        "violations": 0,
    }, (
        "rezono_publisher.publish.publish must emit green rezono:schema with violations=0 directly; "
        f"got checks: {sorted(checks_by_name)}"
    )

    # 4. Negative check: tampering with check_metadata must block publication rather than stamp rezono:schema green.
    tampered = dataclasses.replace(epoch, check_metadata={})
    blocked = False
    try:
        publish.publish(tampered, store.FileStore(work / "archive-tampered"), {"reader": "complete"})
    except publish.Blocked:
        blocked = True
    assert blocked, "tampered check_metadata must be rejected by rezono_publisher/rezono_checker"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: loop/ci_discover.py must read CI shard "
           "counts from build/ pack facts and render the matrix through the single shared renderer "
           "loop.build_job_matrix without copying SHARDS or matrix expansion from scripts/components.py.",
)
def test_ci_discover_shard_counts_come_from_build_facts_via_single_renderer(tmp_path: Path, monkeypatch):
    """Shard counts come from build/ facts and expand through loop.build_job_matrix, never scripts/components.py."""
    import loop.build_job_matrix as build_job_matrix
    import loop.ci_discover as ci_discover
    from scripts import components

    source = CI_DISCOVER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CI_DISCOVER))

    # 1. Structural checks: no SHARDS or legacy selection imports, no local _shard_count copy,
    #    and must import + call loop.build_job_matrix.
    forbidden_component_imports = {
        "SHARDS",
        "shard_count",
        "affected_components",
        "pull_request_selection",
        "pull_request_components",
        "FILE_CONSUMERS",
        "PR_FILE_CONSUMERS",
        "SHARED_READERS",
        "FULL_SELECTION_PATHS",
        "JOB_INPUTS",
    }
    imported_from_components: set[str] = set()
    imports_job_matrix = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"scripts.components", "components"}:
            imported_from_components.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module in {"loop.build_job_matrix", "build_job_matrix"}:
            imports_job_matrix = True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"loop.build_job_matrix", "build_job_matrix"}:
                    imports_job_matrix = True
        if isinstance(node, ast.ImportFrom) and node.module == "loop":
            if any(alias.name == "build_job_matrix" for alias in node.names):
                imports_job_matrix = True

    leaked_imports = sorted(imported_from_components & forbidden_component_imports)
    assert not leaked_imports, (
        f"loop/ci_discover.py still imports shard/selection logic from scripts/components.py: {leaked_imports}"
    )
    defined_funcs = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "_shard_count" not in defined_funcs, (
        "loop/ci_discover.py still defines its own _shard_count copy instead of reading build/ shard facts"
    )
    assert imports_job_matrix, (
        "loop/ci_discover.py must delegate matrix rendering to the single shared renderer loop.build_job_matrix"
    )

    # 2. Schema and pack facts in build/: BuildShardConfig kind + build_shard_config facts.
    from rezono_compiler import facts as fact_files, pack as compiler_pack
    model = compiler_pack.read(BUILD_DIR)
    assert "BuildShardConfig" in {k.cls for k in model.kinds.values()}, (
        "build/ schema must declare BuildShardConfig for shard-count facts"
    )
    shard_rows: dict[str, int] = {}
    for fact_path in fact_files.files(BUILD_DIR):
        raw = yaml.safe_load(fact_path.read_text(encoding="utf-8")) or {}
        for row in raw.get("build_shard_config", ()):
            shard_rows[row["folder"]] = int(row["shards"])
    for expected_folder in ("compiler", "edge/publisher", "examples", "loop"):
        assert expected_folder in shard_rows and shard_rows[expected_folder] >= 1, (
            f"build/facts/ is missing build_shard_config fact for {expected_folder!r}"
        )

    # 3. Behavioral check: poison scripts.components.SHARDS, vary a shard fact in build/facts/,
    #    and verify expand_matrix reflects the build/ fact via loop.build_job_matrix.job_matrix.
    monkeypatch.setattr(components, "SHARDS", {"alpha": 99})
    renderer_calls: list[dict[str, Any]] = []
    orig_job_matrix = build_job_matrix.job_matrix

    def spy_job_matrix(*args, **kwargs):
        renderer_calls.append({"args": args, "kwargs": kwargs})
        return orig_job_matrix(*args, **kwargs)

    monkeypatch.setattr(build_job_matrix, "job_matrix", spy_job_matrix)
    if getattr(ci_discover, "job_matrix", None) is orig_job_matrix:
        monkeypatch.setattr(ci_discover, "job_matrix", spy_job_matrix)

    repo = tmp_path / "shard-repo"
    repo.mkdir()
    shutil.copytree(BUILD_DIR, repo / "build")
    for pack_name in ("std-access", "std-decision", "std-loop", "std-order", "std-time"):
        src = ROOT / "packs" / pack_name
        if src.is_dir():
            shutil.copytree(src, repo / "packs" / pack_name)
    for path in sorted((repo / "build" / "facts").glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "build_shard_config" in doc:
            doc.pop("build_shard_config")
            path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    alpha_dir = repo / "alpha"
    alpha_dir.mkdir()
    (alpha_dir / "pyproject.toml").write_text(
        '[project]\nname = "alpha"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    for idx in range(1, 6):
        (alpha_dir / f"test_case_{idx}.py").write_text(
            f"def test_case_{idx}():\n    assert True\n", encoding="utf-8"
        )

    shards_fact_file = repo / "build" / "facts" / "shards.yaml"
    shards_sources_file = repo / "build" / "facts" / "shards.sources.yaml"
    shards_sources_file.write_text(
        yaml.safe_dump({
            "default": {
                "kind": "tool",
                "name": "shard-config-test",
                "revision": "1" * 40,
                "position": "build/facts/shards.yaml",
            }
        }),
        encoding="utf-8",
    )
    comp = components.Component(folder="alpha", kind="python")

    shards_fact_file.write_text(
        yaml.safe_dump({"build_shard_config": [{"id": "shard-alpha", "folder": "alpha", "shards": 4}]}),
        encoding="utf-8",
    )
    matrix_4 = ci_discover.expand_matrix(root=repo, components=[comp], selected_folders=["alpha"])
    assert renderer_calls, "expand_matrix did not delegate to loop.build_job_matrix.job_matrix"
    assert [item["label"] for item in matrix_4["python"]] == [
        "alpha 1/4", "alpha 2/4", "alpha 3/4", "alpha 4/4"
    ], f"expected 4 shards from build/facts/shards.yaml, got {matrix_4['python']}"

    shards_fact_file.write_text(
        yaml.safe_dump({"build_shard_config": [{"id": "shard-alpha", "folder": "alpha", "shards": 2}]}),
        encoding="utf-8",
    )
    matrix_2 = ci_discover.expand_matrix(root=repo, components=[comp], selected_folders=["alpha"])
    assert [item["label"] for item in matrix_2["python"]] == [
        "alpha 1/2", "alpha 2/2"
    ], f"varying build/facts/shards.yaml to 2 shards did not change rendered matrix: {matrix_2['python']}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: CI observation capture must preserve distinct "
           "event kinds (push/schedule/workflow_dispatch), fail closed without --before instead of "
           "falling back to HEAD, derive real path coverage instead of hardcoded 'unknown', and "
           "record source event time instead of Git commit timestamp.",
)
def test_ci_discover_honest_observation_capture(tmp_path: Path, monkeypatch):
    """CI observation records preserve event kind, event time, non-empty diff guard, and real path coverage."""
    import loop.ci_discover as ci_discover
    from scripts.components import Component

    source = CI_DISCOVER.read_text(encoding="utf-8")

    # 1. Never derive observed_at from Git commit timestamps (%ct).
    uses_commit_time = "--format=%ct" in source
    assert not uses_commit_time, (
        "loop/ci_discover.py must record the source event time, never Git commit timestamp (--format=%ct)"
    )

    # 2. discover_ci_matrix must accept an explicit recorded event_time parameter.
    sig = inspect.signature(ci_discover.discover_ci_matrix)
    assert "event_time" in sig.parameters, (
        "discover_ci_matrix must accept an explicit event_time parameter for the recorded source event time"
    )

    # 3. BuildEvent in build/schema/selection.yaml must support push, schedule, and workflow_dispatch.
    selection_schema = yaml.safe_load((BUILD_DIR / "schema" / "selection.yaml").read_text(encoding="utf-8"))
    allowed_events = set((selection_schema.get("enums") or {}).get("BuildEvent", {}).get("permissible_values") or {})
    for ev in ("pull_request", "merge_group", "push", "schedule", "workflow_dispatch"):
        assert ev in allowed_events, f"build/schema/selection.yaml BuildEvent must permit {ev!r}"

    # 4. Prepare a two-commit repo with old COMMIT_TIME (1700000000), distinct from EVENT_TIME (1810000200).
    repo = tmp_path / "obs-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _create_synthetic_components(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Base commit", env=_commit_env(COMMIT_TIME))
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    (repo / "build").mkdir(exist_ok=True)
    (repo / "build" / "engine-pin.yaml").write_text(f"engine_sha: {base_sha}\n", encoding="utf-8")
    (repo / "alpha" / "engine.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "unmapped.txt").write_text("mystery\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Change alpha and unmapped file", env=_commit_env(COMMIT_TIME))
    head_sha = _git(repo, "rev-parse", "HEAD")

    # 5. push, schedule, and workflow_dispatch keep their real event kind and record EVENT_TIME (not COMMIT_TIME).
    captured: list[dict[str, Any]] = []

    def spy_run_pinned(**kwargs):
        captured.append(kwargs)
        return base_sha, None, None, "spy-stop"

    monkeypatch.setattr(ci_discover, "run_pinned_build_pack", spy_run_pinned)

    for event_name in ("push", "schedule", "workflow_dispatch"):
        captured.clear()
        ci_discover.discover_ci_matrix(
            root=repo,
            run_id=f"run-{event_name}",
            event_name=event_name,
            before_sha=base_sha,
            event_time=EVENT_TIME,
        )
        assert captured, f"discover_ci_matrix did not invoke run_pinned_build_pack for {event_name!r}"
        build_run = captured[-1]["records"]["build_run"][0]
        assert build_run["event"] == event_name, (
            f"event {event_name!r} was misrecorded as {build_run['event']!r} instead of preserving its true kind"
        )
        assert build_run["observed_at"] == EVENT_TIME, (
            f"observed_at must be event time {EVENT_TIME}, not commit time {build_run['observed_at']}"
        )
        assert captured[-1]["knowledge_time"] == EVENT_ISO, (
            f"knowledge_time must match event time {EVENT_ISO}, got {captured[-1]['knowledge_time']!r}"
        )

    # 6. Without --before on a single-commit repo (and with zero SHA), never silently fall back to HEAD (empty diff).
    single = tmp_path / "single-commit"
    single.mkdir()
    _git(single, "init", "-q")
    _create_synthetic_components(single)
    (single / "build").mkdir(exist_ok=True)
    (single / "build" / "engine-pin.yaml").write_text(f"engine_sha: {'1' * 40}\n", encoding="utf-8")
    _git(single, "add", ".")
    _git(single, "commit", "-qm", "Root commit only", env=_commit_env(COMMIT_TIME))

    for missing_before in ("", "0" * 40):
        raised = False
        try:
            res = ci_discover._resolve_git_range(
                single,
                event_name="push",
                base_ref="",
                before_sha=missing_before,
                merge_group_base="",
                merge_group_head="",
            )
        except ValueError:
            raised = True
        else:
            assert res[1] != res[2] or res[3], (
                f"push without --before ({missing_before!r}) silently fell back to HEAD with empty diff: {res!r}"
            )
        assert raised, (
            f"push without valid --before ({missing_before!r}) must fail closed with ValueError"
        )

    # 7. capture_ci_records must not hardcode coverage='unknown' for mapped component files.
    records, _ = ci_discover.capture_ci_records(
        root=repo,
        run_id="run-cov",
        build_event="pull_request",
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=base_sha,
        observed_at=EVENT_TIME,
        components=[Component(folder=name, kind="python") for name in SUITES],
        changed_paths=["alpha/engine.py", "unmapped.txt"],
    )
    by_path = {row["path"]: row for row in records["build_path"]}
    assert by_path["alpha/engine.py"]["coverage"] == "mapped", (
        "capture_ci_records must classify component path 'alpha/engine.py' as 'mapped', "
        f"not hardcoded {by_path['alpha/engine.py']['coverage']!r}"
    )
    assert by_path["unmapped.txt"]["coverage"] == "unknown", (
        f"unmapped path 'unmapped.txt' must stay 'unknown', got {by_path['unmapped.txt']['coverage']!r}"
    )
    readers = records.get("build_path_reader") or []
    assert any(
        r.get("path") == by_path["alpha/engine.py"]["id"] and r.get("component") == "alpha"
        for r in readers
    ), f"mapped path 'alpha/engine.py' must emit a build_path_reader for 'alpha', got {readers!r}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: loop/ci_discover.py must never default "
           "knowledge_time to hardcoded test date '2027-01-15T08:00:00Z' and must not expose "
           "a --pin-sha CLI override bypassing build/engine-pin.yaml.",
)
def test_ci_discover_forbids_hardcoded_knowledge_time_and_pin_sha_override(tmp_path: Path):
    """knowledge_time is required without hardcoded test dates, and --pin-sha cannot bypass build/engine-pin.yaml."""
    import loop.ci_discover as ci_discover

    source = CI_DISCOVER.read_text(encoding="utf-8")

    # 1. No hardcoded test date anywhere in production loop/ci_discover.py.
    has_hardcoded_date = "2027-01-15T08:00:00Z" in source
    assert not has_hardcoded_date, (
        "loop/ci_discover.py still hardcodes test date '2027-01-15T08:00:00Z'"
    )

    # 2. evaluate_coordinator_state requires explicit knowledge_time (never a hardcoded string default).
    coord_sig = inspect.signature(ci_discover.evaluate_coordinator_state)
    kt_param = coord_sig.parameters.get("knowledge_time")
    assert kt_param is not None, "evaluate_coordinator_state must accept knowledge_time"
    assert kt_param.default in (inspect.Parameter.empty, None), (
        f"evaluate_coordinator_state.knowledge_time must not have a hardcoded default, got {kt_param.default!r}"
    )

    records_file = tmp_path / "records.yaml"
    records_file.write_text(yaml.safe_dump({"build_run": []}), encoding="utf-8")

    rejected_python = False
    try:
        ci_discover.evaluate_coordinator_state(root=tmp_path, records_path=records_file)
    except (TypeError, ValueError):
        rejected_python = True
    assert rejected_python, (
        "evaluate_coordinator_state(records_path=...) without explicit knowledge_time "
        "must fail with TypeError or ValueError"
    )

    rejected_cli_kt = False
    try:
        rc = ci_discover.main(["coordinator-state", "--root", str(tmp_path), "--records", str(records_file)])
    except (SystemExit, ValueError) as exc:
        rejected_cli_kt = isinstance(exc, ValueError) or (exc.code not in (0, None))
    else:
        rejected_cli_kt = rc != 0
    assert rejected_cli_kt, (
        "CLI 'coordinator-state --records ...' without explicit --knowledge-time must fail"
    )

    # 3. No --pin-sha CLI override or pin_sha API parameter bypassing build/engine-pin.yaml.
    has_pin_sha_flag = "--pin-sha" in source
    assert not has_pin_sha_flag, (
        "loop/ci_discover.py must not provide a --pin-sha CLI flag that bypasses build/engine-pin.yaml"
    )
    for func in (
        ci_discover.run_pinned_build_pack,
        ci_discover.discover_ci_matrix,
        ci_discover.evaluate_coordinator_state,
    ):
        assert "pin_sha" not in inspect.signature(func).parameters, (
            f"{func.__name__} must not accept pin_sha override bypassing build/engine-pin.yaml"
        )

    for subcmd in ("ci-matrix", "coordinator-state"):
        rejected_pin_override = False
        try:
            ci_discover.main([subcmd, "--pin-sha", "a" * 40])
        except SystemExit as exc:
            rejected_pin_override = exc.code not in (0, None)
        assert rejected_pin_override, (
            f"CLI '{subcmd} --pin-sha <sha>' must be rejected so build/engine-pin.yaml cannot be bypassed"
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: end-to-end behavioral test of loop/ci_discover.py "
           "(ci-matrix and coordinator-state) against independent hand-written records covering happy "
           "path, fail-closed safe_mode, and role-scoped publication. "
           "Waits for loop/tests/test_ci_discover_quality.py--test_rezono_schema_check_emitted_by_publisher_never_synthesized_by_ci_discover, "
           "loop/tests/test_ci_discover_quality.py--test_ci_discover_honest_observation_capture, and "
           "loop/tests/test_ci_discover_quality.py--test_ci_discover_forbids_hardcoded_knowledge_time_and_pin_sha_override.",
)
def test_ci_discover_end_to_end_against_hand_written_records(tmp_path: Path):
    """End-to-end verification of ci-matrix and coordinator-state over hand-written records."""
    import loop.ci_discover as ci_discover

    # Guard prerequisites as clean AssertionErrors before calling updated signatures.
    synthesizes_schema = "rezono:schema" in _all_ci_discover_code_literals()
    assert not synthesizes_schema, (
        "loop/ci_discover.py still synthesizes 'rezono:schema' instead of relying on publisher/checker"
    )
    assert "event_time" in inspect.signature(ci_discover.discover_ci_matrix).parameters, (
        "discover_ci_matrix must accept explicit event_time"
    )
    has_hardcoded_date = "2027-01-15T08:00:00Z" in CI_DISCOVER.read_text(encoding="utf-8")
    assert not has_hardcoded_date, (
        "loop/ci_discover.py still carries hardcoded test date '2027-01-15T08:00:00Z'"
    )

    repo, engine_sha, base_sha, head_sha = _make_isolated_pinned_repo(tmp_path)

    # --- Scenario A: ci-matrix happy path against hand-written selection records + admitted evidence ---
    evidence_dir = tmp_path / "selection-evidence"
    evidence_dir.mkdir()
    sel_records, sel_sidecar = _build_selection_records_and_evidence(
        repo,
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=engine_sha,
        run_id="run-e2e",
        observed_at=EVENT_TIME,
        evidence_dir=evidence_dir,
    )
    happy_ci = ci_discover.discover_ci_matrix(
        root=repo,
        run_id="run-e2e",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
        records_override=sel_records,
        sources_sidecar_override=sel_sidecar,
        evidence_dir=evidence_dir,
    )
    assert happy_ci["engine_sha"] == engine_sha
    assert happy_ci["engine_error"] is None, f"unexpected engine error: {happy_ci['engine_error']}"
    assert happy_ci["outcome"] == {
        "run": "run-e2e",
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "use": ["alpha", "beta", "gamma"],
        "findings": [],
    }
    assert [item["folder"] for item in happy_ci["matrix"]["python"]] == ["alpha", "beta", "gamma"]

    # --- Scenario B: ci-matrix fail-closed safe_mode on invalid self-pin ---
    bad_pin = tmp_path / "self-pin.yaml"
    bad_pin.write_text(f"engine_sha: {head_sha}\n", encoding="utf-8")
    safe_ci = ci_discover.discover_ci_matrix(
        root=repo,
        run_id="run-safe",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
        pin_path=bad_pin,
        records_override=sel_records,
        sources_sidecar_override=sel_sidecar,
        evidence_dir=evidence_dir,
    )
    assert safe_ci["outcome"] == {
        "run": "run-safe",
        "source": "safe_mode",
        "safe_mode": True,
        "safe_mode_reason": "engine-failure",
        "use": ["alpha", "beta", "gamma", "spare"],
        "findings": [{
            "kind": "safe_mode",
            "run": "run-safe",
            "surface": "ci_selection",
            "reason": "engine-failure",
        }],
    }
    assert sorted({item["folder"] for item in safe_ci["matrix"]["python"]}) == [
        "alpha", "beta", "gamma", "spare"
    ]

    # --- Scenario C: coordinator-state happy path + role-scoped publication ---
    coord_records, coord_sidecar = _build_coordinator_records(
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=engine_sha,
        run_id="run-coord",
        observed_at=EVENT_TIME,
    )
    coord_file = tmp_path / "coordinator.yaml"
    coord_file.write_text(yaml.safe_dump(coord_records), encoding="utf-8")
    (tmp_path / "coordinator.sources.yaml").write_text(yaml.safe_dump(coord_sidecar), encoding="utf-8")

    coord_state = ci_discover.evaluate_coordinator_state(
        root=repo,
        run_id="run-coord",
        records_path=coord_file,
        role="coordinator",
        role_mode="may_read",
        knowledge_time=EVENT_ISO,
    )
    assert coord_state["source"] == "pack", f"expected pack coordinator state, got {coord_state}"
    assert coord_state["safe_mode"] is False
    assert coord_state["assign_new_tasks"] is True
    assert {row["task"] for row in coord_state["ready"]} == {"task-core", "task-lang"}
    assert [(row["task"], row["token"]) for row in coord_state["waiting"]] == [
        ("task-wait", "compiled-core")
    ]
    assert [(row["task"], row["reason"]) for row in coord_state["stuck"]] == [
        ("task-stuck", "terminal-refusal")
    ]
    assert coord_state["claim_release_plan"] == [{
        "claim": "task/expired",
        "generation": _claim_generation("task/expired"),
        "reason": "lease-ended",
    }]
    assert coord_state["claim_held"] == [{"claim": "task/active", "reason": "lease-active"}]
    assert coord_state["findings"] == []

    # Unprivileged role lacks read capability and must never receive tasks or claim release plans
    # (verified pack publication with empty role-filtered relations, not a safe_mode crash).
    denied_state = ci_discover.evaluate_coordinator_state(
        root=repo,
        run_id="run-coord",
        records_path=coord_file,
        role="unprivileged",
        role_mode="may_read",
        knowledge_time=EVENT_ISO,
    )
    assert denied_state["source"] == "pack", f"expected verified pack publication for unprivileged role, got {denied_state}"
    assert denied_state["safe_mode"] is False
    assert denied_state["findings"] == []
    assert denied_state["ready"] == []
    assert denied_state["waiting"] == []
    assert denied_state["stuck"] == []
    assert denied_state["claim_release_plan"] == []
    assert denied_state["claim_held"] == []

    # --- Scenario D: coordinator-state fail-closed safe_mode (engine failure and invalid manifest) ---
    coord_safe_engine = ci_discover.evaluate_coordinator_state(
        root=repo,
        run_id="run-coord",
        records_path=coord_file,
        pin_path=bad_pin,
        role="coordinator",
        role_mode="may_read",
        knowledge_time=EVENT_ISO,
    )
    assert coord_safe_engine == {
        "run": "run-coord",
        "source": "safe_mode",
        "safe_mode": True,
        "safe_mode_reason": "engine-failure",
        "assign_new_tasks": False,
        "ready": [],
        "waiting": [],
        "stuck": [],
        "claim_release_plan": [],
        "claim_held": [],
        "findings": [{
            "kind": "safe_mode",
            "run": "run-coord",
            "surface": "coordinator",
            "reason": "engine-failure",
        }],
    }

    incomplete_manifest = tmp_path / "manifest-no-schema.json"
    incomplete_manifest.write_text(
        json.dumps({"checks": [{"name": "rezono:proofs", "status": "green", "violations": 0}]}),
        encoding="utf-8",
    )
    empty_rows = tmp_path / "rows-empty.json"
    empty_rows.write_text(
        json.dumps({
            "build_task_ready": [],
            "build_task_waiting": [],
            "build_task_stuck": [],
            "build_claim_release_plan": [],
            "build_claim_held": [],
        }),
        encoding="utf-8",
    )
    coord_safe_manifest = ci_discover.evaluate_coordinator_state(
        root=repo,
        run_id="run-coord",
        manifest_path=incomplete_manifest,
        rows_path=empty_rows,
        knowledge_time=EVENT_ISO,
    )
    assert coord_safe_manifest == {
        "run": "run-coord",
        "source": "safe_mode",
        "safe_mode": True,
        "safe_mode_reason": "invalid-publication",
        "assign_new_tasks": False,
        "ready": [],
        "waiting": [],
        "stuck": [],
        "claim_release_plan": [],
        "claim_held": [],
        "findings": [{
            "kind": "safe_mode",
            "run": "run-coord",
            "surface": "coordinator",
            "reason": "invalid-publication",
        }],
    }
