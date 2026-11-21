"""Behavioral and strict red tests for ``loop/ci_discover.py``.

Covers ``decisions/build-reconciliation.md``, ``decisions/tooling-does-not-decide.md``,
and ``decisions/no-green-by-cheapest-route.md`` without source-text checks or day-number
shortcuts:

- Standalone green regression test for fail-closed ``safe_mode`` across both ``ci-matrix``
  and ``coordinator-state`` (on invalid engine pin and on manifest missing ``rezono:schema``).
- Five strict ``pytest.mark.xfail(strict=True, raises=AssertionError, ...)`` tests:
  1. ``rezono:schema`` emitted directly by ``rezono_publisher`` / ``rezono_checker``, never
     synthesized by ``loop/ci_discover.py``.
  2. CI shard counts sourced from ``BuildShardConfig`` facts in ``build/facts/`` (with
     ``.sources.yaml`` provenance) and rendered via the single shared renderer
     ``loop.build_job_matrix``.
  3. Honest CI observation capture: distinct event kinds (``push``, ``schedule``,
     ``workflow_dispatch``), fail-closed missing ``--before``, real path coverage, and
     explicit source ``event_time`` instead of Git commit timestamps.
  4. Required ``knowledge_time`` without hardcoded test-date defaults, and no ``--pin-sha``
     override bypassing ``build/engine-pin.yaml``.
  5. End-to-end subprocess verification of ``loop/ci_discover.py`` (``ci-matrix`` with real
     capture — no ``records_override`` — and ``coordinator-state`` with native dates only and
     role-scoped publication).
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_DISCOVER = ROOT / "loop" / "ci_discover.py"
BUILD_DIR = ROOT / "build"

COMMIT_TIME = 1_700_000_000  # 2023-11-14T22:13:20Z (deliberately far from EVENT_TIME)
EVENT_TIME = 1_810_000_200   # 2027-05-11T01:50:00Z (distinct from COMMIT_TIME and 2027-01-15)
EVENT_ISO = "2027-05-11T01:50:00Z"
EVENT_DATE = "2027-05-11"
LEASE_SECONDS = 4 * 60 * 60
SUITES = ("alpha", "beta", "gamma", "spare")
AUTHORITY_PATH = "observer/build-readers.json"

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


def _copy_engine_tree(dst: Path) -> None:
    import loop.ci_discover as ci_discover

    def _ignore(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name in _COPY_SKIP]

    for rel in ci_discover._PINNED_ARCHIVE_PATHS:
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


def _make_lightweight_candidate_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a fast 2-commit synthetic repo with the four suites and an engine-pin file."""
    repo = tmp_path / "candidate"
    repo.mkdir()
    _git(repo, "init", "-q")
    _create_synthetic_components(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Base commit", env=_commit_env(COMMIT_TIME))
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)

    (repo / "build").mkdir(exist_ok=True)
    (repo / "build" / "engine-pin.yaml").write_text(f"engine_sha: {base_sha}\n", encoding="utf-8")
    (repo / "alpha" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Candidate change in alpha", env=_commit_env(COMMIT_TIME))
    head_sha = _git(repo, "rev-parse", "HEAD")
    return repo, base_sha, head_sha


def _make_stub_publisher_repo_without_schema_check(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a minimal 2-commit repo whose pinned publisher omits ``rezono:schema``."""
    repo = tmp_path / "stub-schema-repo"
    repo.mkdir()
    _git(repo, "init", "-q")

    (repo / "build").mkdir(parents=True)
    (repo / "build" / "pack.yaml").write_text("name: stub-build\nversion: 0.1.0\n", encoding="utf-8")

    # Minimal stub packages under the pinned engine paths required by ci_discover._extract_pinned_engine.
    for pkg_dir, mod_name in (
        ("canon", "rezono_canon"),
        ("admission", "rezono_admission"),
        ("contracts/python", "rezono_contracts"),
    ):
        target = repo / pkg_dir / mod_name
        target.mkdir(parents=True)
        (target / "__init__.py").write_text("", encoding="utf-8")

    compiler_pkg = repo / "compiler" / "rezono_compiler"
    compiler_pkg.mkdir(parents=True)
    (compiler_pkg / "__init__.py").write_text("", encoding="utf-8")
    (compiler_pkg / "pack.py").write_text("def read(build_dir):\n    return None\n", encoding="utf-8")

    checker_pkg = repo / "checker" / "rezono_checker"
    checker_pkg.mkdir(parents=True)
    (checker_pkg / "__init__.py").write_text(
        "def check_epoch(*args, **kwargs):\n    return {'valid': True, 'findings': []}\n",
        encoding="utf-8",
    )
    (checker_pkg / "metadata.py").write_text("def check(bundle, meta):\n    return []\n", encoding="utf-8")
    (checker_pkg / "evidence.py").write_text(
        "class Evidence:\n    def __init__(self, **kwargs):\n        self.__dict__.update(kwargs)\n",
        encoding="utf-8",
    )
    (checker_pkg / "rules.py").write_text(
        "def load_rules(doc):\n    return {}\n"
        "def derived_relations(doc, obj):\n    return set()\n"
        "def load_seals(doc):\n    return ()\n",
        encoding="utf-8",
    )

    import loop.ci_discover as ci_discover

    pub_rel = next(p for p in ci_discover._PINNED_ARCHIVE_PATHS if p.endswith("/publisher"))
    pub_pkg = repo / pub_rel / "rezono_publisher"
    pub_pkg.mkdir(parents=True)
    (pub_pkg / "__init__.py").write_text("", encoding="utf-8")
    (pub_pkg / "store.py").write_text(
        "from pathlib import Path\n"
        "class FileStore:\n"
        "    def __init__(self, root):\n"
        "        self.root = Path(root)\n"
        "        self.root.mkdir(parents=True, exist_ok=True)\n"
        "    def uri(self, key):\n"
        "        return f's3://rezono/{key}'\n"
        "    def put_new(self, key, data):\n"
        "        p = self.root / key\n"
        "        p.parent.mkdir(parents=True, exist_ok=True)\n"
        "        p.write_bytes(data)\n"
        "    def get(self, key):\n"
        "        p = self.root / key\n"
        "        return p.read_bytes() if p.is_file() else None\n",
        encoding="utf-8",
    )
    (pub_pkg / "batch.py").write_text(
        "class _Epoch:\n"
        "    rules = '{}'\n"
        "    bundle = ''\n"
        "    check_metadata = None\n"
        "def epoch(*args, **kwargs):\n"
        "    return _Epoch()\n",
        encoding="utf-8",
    )
    (pub_pkg / "publish.py").write_text(
        "import hashlib, json\n"
        "def calc_ir(epoch):\n"
        "    return None\n"
        "def publish(epoch, archive, roles):\n"
        "    role = next(iter(roles))\n"
        "    sel_bytes = json.dumps([{'key': ['r1', 'alpha', 'change']}]).encode()\n"
        "    full_bytes = json.dumps([]).encode()\n"
        "    wit_bytes = json.dumps({'witnesses': [], 'calc_witnesses': []}).encode()\n"
        "    archive.put_new('sel.json', sel_bytes)\n"
        "    archive.put_new('full.json', full_bytes)\n"
        "    archive.put_new('wit.json', wit_bytes)\n"
        "    return {\n"
        "        'checks': [\n"
        "            {'name': 'missing_required', 'status': 'green', 'violations': 0},\n"
        "            {'name': 'rezono:proofs', 'status': 'green', 'violations': 0},\n"
        "        ],\n"
        "        'snapshots': [\n"
        "            {'role': role, 'relation': 'build_selected_job', 'uri': archive.uri('sel.json'),\n"
        "             'sha256': hashlib.sha256(sel_bytes).hexdigest(), 'complete': True, 'full': True},\n"
        "            {'role': role, 'relation': 'build_full_selection', 'uri': archive.uri('full.json'),\n"
        "             'sha256': hashlib.sha256(full_bytes).hexdigest(), 'complete': True, 'full': True},\n"
        "        ],\n"
        "        'witnesses': [\n"
        "            {'role': role, 'uri': archive.uri('wit.json'),\n"
        "             'sha256': hashlib.sha256(wit_bytes).hexdigest()},\n"
        "        ],\n"
        "    }\n",
        encoding="utf-8",
    )

    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Seed stub pinned engine without rezono:schema", env=_commit_env(COMMIT_TIME))
    engine_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", engine_sha)

    (repo / "build" / "engine-pin.yaml").write_text(f"engine_sha: {engine_sha}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Pin stub engine", env=_commit_env(COMMIT_TIME))
    head_sha = _git(repo, "rev-parse", "HEAD")
    return repo, engine_sha, head_sha


def _archived_ref(key: str, value: Any) -> dict[str, str]:
    from rezono_canon import canonical_sha256

    return {"file": key, "uri": f"s3://rezono/{key}", "sha256": canonical_sha256(value)}


def _write_selection_evidence(
    repo: Path,
    *,
    base_sha: str,
    head_sha: str,
    engine_sha: str,
    run_id: str,
    observed_at: int,
    evidence_dir: Path,
) -> str:
    """Write independent admitted completeness evidence for ``alpha/engine.py`` and return its receipt ID."""
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
    return receipt_id


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
    """Hand-write independent task, claim, and role records using native dates only (no day numbers)."""
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
            "title": "Observed reference date",
            "date": EVENT_DATE,
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


def test_ci_discover_fail_closed_safe_mode_for_ci_matrix_and_coordinator_state(tmp_path: Path):
    """Both ci-matrix and coordinator-state fail closed to safe_mode on invalid pin or missing rezono:schema."""
    from loop.build_cutover import select_suites

    repo, base_sha, head_sha = _make_lightweight_candidate_repo(tmp_path)
    bad_pin = tmp_path / "self-pin.yaml"
    bad_pin.write_text(f"engine_sha: {head_sha}\n", encoding="utf-8")

    # 1. ci-matrix fail-closed safe_mode on self-pin violation via real subprocess.
    ci_proc = subprocess.run(
        [
            sys.executable,
            str(CI_DISCOVER),
            "ci-matrix",
            "--root",
            str(repo),
            "--run",
            "run-safe",
            "--event",
            "pull_request",
            "--base-ref",
            "main",
            "--pin",
            str(bad_pin),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ci_proc.returncode == 0, f"ci-matrix failed unexpectedly: {ci_proc.stderr}\n{ci_proc.stdout}"
    safe_ci = json.loads(ci_proc.stdout)
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

    # 2. ci-matrix selection fails closed to safe_mode on a manifest lacking rezono:schema.
    incomplete_manifest_doc = {"checks": [{"name": "rezono:proofs", "status": "green", "violations": 0}]}
    ci_missing_schema = select_suites(
        run="run-safe",
        manifest=incomplete_manifest_doc,
        rows={"build_selected_job": [], "build_full_selection": []},
        engine_error=None,
        universe=SUITES,
    )
    assert ci_missing_schema == {
        "run": "run-safe",
        "source": "safe_mode",
        "safe_mode": True,
        "safe_mode_reason": "invalid-publication",
        "use": ["alpha", "beta", "gamma", "spare"],
        "findings": [{
            "kind": "safe_mode",
            "run": "run-safe",
            "surface": "ci_selection",
            "reason": "invalid-publication",
        }],
    }

    # 3. coordinator-state fail-closed safe_mode on self-pin violation via real subprocess.
    coord_records, coord_sidecar = _build_coordinator_records(
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=base_sha,
        run_id="run-coord-safe",
        observed_at=EVENT_TIME,
    )
    coord_file = tmp_path / "coordinator.yaml"
    coord_file.write_text(yaml.safe_dump(coord_records), encoding="utf-8")
    (tmp_path / "coordinator.sources.yaml").write_text(yaml.safe_dump(coord_sidecar), encoding="utf-8")

    coord_engine_proc = subprocess.run(
        [
            sys.executable,
            str(CI_DISCOVER),
            "coordinator-state",
            "--root",
            str(repo),
            "--run",
            "run-coord-safe",
            "--records",
            str(coord_file),
            "--pin",
            str(bad_pin),
            "--role",
            "coordinator",
            "--role-mode",
            "may_read",
            "--knowledge-time",
            EVENT_ISO,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert coord_engine_proc.returncode == 0, (
        f"coordinator-state failed unexpectedly: {coord_engine_proc.stderr}\n{coord_engine_proc.stdout}"
    )
    assert json.loads(coord_engine_proc.stdout) == {
        "run": "run-coord-safe",
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
            "run": "run-coord-safe",
            "surface": "coordinator",
            "reason": "engine-failure",
        }],
    }

    # 4. coordinator-state fail-closed safe_mode on a manifest lacking rezono:schema via real subprocess.
    incomplete_manifest = tmp_path / "manifest-no-schema.json"
    incomplete_manifest.write_text(json.dumps(incomplete_manifest_doc), encoding="utf-8")
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
    coord_manifest_proc = subprocess.run(
        [
            sys.executable,
            str(CI_DISCOVER),
            "coordinator-state",
            "--root",
            str(repo),
            "--run",
            "run-coord-safe",
            "--manifest",
            str(incomplete_manifest),
            "--rows",
            str(empty_rows),
            "--knowledge-time",
            EVENT_ISO,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert coord_manifest_proc.returncode == 0, (
        f"coordinator-state manifest check failed unexpectedly: {coord_manifest_proc.stderr}"
    )
    assert json.loads(coord_manifest_proc.stdout) == {
        "run": "run-coord-safe",
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
            "run": "run-coord-safe",
            "surface": "coordinator",
            "reason": "invalid-publication",
        }],
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: rezono:schema must be emitted directly by "
           "rezono_publisher/rezono_checker and never synthesized by loop/ci_discover.py.",
)
def test_rezono_schema_check_emitted_by_publisher_never_synthesized_by_ci_discover(tmp_path: Path):
    """Behaviorally verify rezono_publisher emits rezono:schema and loop/ci_discover.py never fabricates it."""
    from loop.build_cutover import select_suites
    import loop.ci_discover as ci_discover

    # 1. Behavioral check on loop/ci_discover.py: when a pinned publisher omits rezono:schema,
    #    run_pinned_build_pack must NOT synthesize rezono:schema into manifest['checks'].
    stub_repo, engine_sha, _ = _make_stub_publisher_repo_without_schema_check(tmp_path)
    got_sha, stub_manifest, stub_rows, stub_err = ci_discover.run_pinned_build_pack(
        root=stub_repo,
        records={},
        sources_sidecar=None,
        knowledge_time=EVENT_ISO,
    )
    assert stub_err is None, f"stub pinned engine failed unexpectedly: {stub_err}"
    assert got_sha == engine_sha and isinstance(stub_manifest, dict) and isinstance(stub_rows, dict)
    stub_check_names = [c.get("name") for c in stub_manifest.get("checks", []) if isinstance(c, dict)]
    assert "rezono:schema" not in stub_check_names, (
        "loop/ci_discover.py fabricated 'rezono:schema' when the pinned publisher did not emit it: "
        f"{stub_manifest.get('checks')}"
    )
    rejected = select_suites(
        run="r1",
        manifest=stub_manifest,
        rows=stub_rows,
        engine_error=stub_err,
        universe=("alpha", "beta"),
    )
    assert rejected["safe_mode"] is True and rejected["safe_mode_reason"] == "invalid-publication"

    # 2. Direct behavioral check on real rezono_publisher + rezono_checker over a minimal pack.
    from rezono_publisher import batch, publish, store

    pack_dir = tmp_path / "mini-pack"
    for sub in ("schema", "rules", "labels", "messages", "facts"):
        (pack_dir / sub).mkdir(parents=True)
    (pack_dir / "pack.yaml").write_text(
        "name: mini-schema-probe\nversion: 0.1.0\ndefault_language: en\n", encoding="utf-8"
    )
    (pack_dir / "schema" / "item.yaml").write_text(
        "id: https://rezono.example/mini-schema-probe\n"
        "name: mini_schema_probe\n"
        "imports: [linkml:types]\n"
        "default_range: string\n"
        "annotations:\n  layer: facts\n"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      label: {required: true}\n",
        encoding="utf-8",
    )
    (pack_dir / "channels.yaml").write_text("kinds:\n  - {kind: item, shape: pill}\n", encoding="utf-8")
    (pack_dir / "labels" / "en.yaml").write_text(
        "item: item\nitem.label: label\nitem_seen: item seen\n",
        encoding="utf-8",
    )
    (pack_dir / "messages" / "en.mf2").write_text(
        "@locale en\n"
        "---\n"
        "arrow.total = Each {$kind} has exactly one {$arrow}.\n"
        "arrow.partial = Each {$kind} has at most one {$arrow}.\n"
        "attribute.total = Each {$kind} has exactly one {$attribute}.\n"
        "attribute.partial = Each {$kind} has at most one {$attribute}.\n"
        "attribute.many.total = Each {$kind} has at least one {$attribute}.\n"
        "attribute.many.partial = Each {$kind} may have more than one {$attribute}.\n"
        "is_a = Each {$kind} is a {$parent}.\n"
        "unique_key = Each {$key} belongs to at most one {$kind}.\n"
        "path_equation = For each {$kind}, {$equation} holds.\n",
        encoding="utf-8",
    )
    (pack_dir / "rules" / "item.dl").write_text(
        ".decl item_seen(id: symbol)\nitem_seen(x) :- item(x).\n.output item_seen\n",
        encoding="utf-8",
    )
    (pack_dir / "facts" / "input.yaml").write_text(
        yaml.safe_dump({"item": [{"id": "i1", "label": "one"}]}), encoding="utf-8"
    )
    (pack_dir / "facts" / "input.sources.yaml").write_text(
        yaml.safe_dump({
            "default": {"kind": "tool", "name": "schema-check-test", "revision": "1" * 40, "position": "i1"}
        }),
        encoding="utf-8",
    )

    archive = store.FileStore(tmp_path / "mini-archive")
    epoch = batch.epoch(pack_dir, epoch=1, knowledge_time=EVENT_ISO, sources=[("facts", "input")])
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

    # 3. Negative check: tampering with check_metadata must block publication rather than stamp rezono:schema green.
    tampered = dataclasses.replace(epoch, check_metadata={})
    with pytest.raises(publish.Blocked):
        publish.publish(tampered, store.FileStore(tmp_path / "mini-archive-tampered"), {"reader": "complete"})


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/tooling-does-not-decide.md: loop/ci_discover.py must read CI shard "
           "counts from BuildShardConfig facts in build/facts/ (with .sources.yaml provenance) "
           "and render the matrix through the single shared renderer loop.build_job_matrix.",
)
def test_ci_discover_shard_counts_come_from_build_facts_via_single_renderer(tmp_path: Path, monkeypatch):
    """Shard counts come from build/ facts and expand through loop.build_job_matrix, never scripts/components.py."""
    import loop.build_job_matrix as build_job_matrix
    import loop.ci_discover as ci_discover
    from scripts import components

    # 1. Behavioral check first: poison scripts.components.SHARDS, vary a shard fact in build/facts/,
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

    # 2. Schema, independent repository expectations, and .sources.yaml provenance in ROOT/build/.
    from rezono_compiler import facts as fact_files, pack as compiler_pack

    model = compiler_pack.read(BUILD_DIR)
    shard_kind = next((k for k in model.kinds.values() if k.cls == "BuildShardConfig"), None)
    assert shard_kind is not None, "build/ schema must declare BuildShardConfig for shard-count facts"
    assert {"folder", "shards"} <= set(shard_kind.slots), (
        f"BuildShardConfig must declare 'folder' and 'shards' slots, got {sorted(shard_kind.slots)}"
    )

    discovered_folders = {c.folder for c in components.discover_components(ROOT)}
    shard_rows: dict[str, int] = {}
    shard_fact_files: list[Path] = []
    for fact_path in fact_files.files(BUILD_DIR):
        raw = yaml.safe_load(fact_path.read_text(encoding="utf-8")) or {}
        if "build_shard_config" not in raw:
            continue
        shard_fact_files.append(fact_path)
        fact_files.load(model, fact_path)
        sidecar_path = fact_path.with_suffix(".sources.yaml")
        assert sidecar_path.is_file(), (
            f"shard fact file {fact_path.relative_to(ROOT).as_posix()} is missing its provenance sidecar "
            f"{sidecar_path.relative_to(ROOT).as_posix()}"
        )
        sidecar_doc = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
        assert isinstance(sidecar_doc, dict) and sidecar_doc, (
            f"provenance sidecar {sidecar_path.relative_to(ROOT).as_posix()} must be a non-empty YAML mapping"
        )
        for row in raw["build_shard_config"]:
            shard_rows[row["folder"]] = int(row["shards"])

    assert shard_fact_files, "build/facts/ must contain a BuildShardConfig fact file"
    assert set(shard_rows) <= discovered_folders, (
        f"build_shard_config names unknown repository folders: {sorted(set(shard_rows) - discovered_folders)}"
    )
    # Independent explicit expectations (never derived from components.SHARDS):
    # both compiler and loop are multi-shard suites, and every declared suite has shards >= 1.
    assert shard_rows.get("compiler", 0) >= 2, f"expected multi-shard fact for 'compiler', got {shard_rows}"
    assert shard_rows.get("loop", 0) >= 2, f"expected multi-shard fact for 'loop', got {shard_rows}"
    assert all(count >= 1 for count in shard_rows.values()), f"invalid shard counts: {shard_rows}"


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

    # 1. Prepare a two-commit repo with old COMMIT_TIME (1700000000), distinct from EVENT_TIME (1810000200).
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

    # 2. Behavioral check: push, schedule, and workflow_dispatch keep their true event kind and record EVENT_TIME.
    captured: list[dict[str, Any]] = []

    def spy_run_pinned(**kwargs):
        captured.append(kwargs)
        return base_sha, None, None, "spy-stop"

    monkeypatch.setattr(ci_discover, "run_pinned_build_pack", spy_run_pinned)

    for event_name in ("push", "schedule", "workflow_dispatch"):
        captured.clear()
        try:
            ci_discover.discover_ci_matrix(
                root=repo,
                run_id=f"run-{event_name}",
                event_name=event_name,
                before_sha=base_sha,
                event_time=EVENT_TIME,
            )
        except TypeError as exc:
            raise AssertionError(
                f"discover_ci_matrix must accept explicit event_time instead of using Git commit time: {exc}"
            ) from exc
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

    # 3. BuildEvent in build/schema/selection.yaml must permit push, schedule, and workflow_dispatch.
    selection_schema = yaml.safe_load((BUILD_DIR / "schema" / "selection.yaml").read_text(encoding="utf-8"))
    allowed_events = set((selection_schema.get("enums") or {}).get("BuildEvent", {}).get("permissible_values") or {})
    for ev in ("pull_request", "merge_group", "push", "schedule", "workflow_dispatch"):
        assert ev in allowed_events, f"build/schema/selection.yaml BuildEvent must permit {ev!r}"

    # 4. Without --before on a single-commit repo (empty or zero SHA), fail closed strictly with ValueError.
    single = tmp_path / "single-commit"
    single.mkdir()
    _git(single, "init", "-q")
    _create_synthetic_components(single)
    (single / "build").mkdir(exist_ok=True)
    (single / "build" / "engine-pin.yaml").write_text(f"engine_sha: {'1' * 40}\n", encoding="utf-8")
    _git(single, "add", ".")
    _git(single, "commit", "-qm", "Root commit only", env=_commit_env(COMMIT_TIME))

    for missing_before in ("", "0" * 40):
        with pytest.raises(ValueError):
            ci_discover._resolve_git_range(
                single,
                event_name="push",
                base_ref="",
                before_sha=missing_before,
                merge_group_base="",
                merge_group_head="",
            )

    # 5. capture_ci_records must classify mapped component paths honestly rather than hardcoding 'unknown'.
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
    reason="M2: decisions/build-reconciliation.md: loop/ci_discover.py must require explicit "
           "knowledge_time without hardcoded test-date defaults and must reject --pin-sha "
           "CLI/API overrides bypassing build/engine-pin.yaml.",
)
def test_ci_discover_forbids_hardcoded_knowledge_time_and_pin_sha_override(tmp_path: Path):
    """knowledge_time is required without hardcoded test dates, and --pin-sha cannot bypass build/engine-pin.yaml."""
    import loop.ci_discover as ci_discover

    # 1. evaluate_coordinator_state requires explicit knowledge_time (no hardcoded default string).
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

    # 2. No pin_sha API parameter or --pin-sha CLI override bypassing build/engine-pin.yaml.
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
    reason="M3: decisions/build-reconciliation.md: end-to-end subprocess verification of "
           "loop/ci_discover.py (ci-matrix with real capture and coordinator-state with native "
           "dates and role-scoped publication) against independent hand-written records. "
           "Waits for loop/tests/test_ci_discover_quality.py--test_rezono_schema_check_emitted_by_publisher_never_synthesized_by_ci_discover, "
           "loop/tests/test_ci_discover_quality.py--test_ci_discover_honest_observation_capture, "
           "loop/tests/test_ci_discover_quality.py--test_ci_discover_forbids_hardcoded_knowledge_time_and_pin_sha_override, "
           "compiler/tests/test_std_decision_dates.py--test_std_decision_rules_read_dates, and "
           "compiler/tests/test_std_decision_day_retirement.py--test_std_decision_retires_day_numbers_and_coupling_rules.",
)
def test_ci_discover_end_to_end_against_hand_written_records(tmp_path: Path):
    """End-to-end subprocess verification of ci-matrix (real capture) and coordinator-state (role publication)."""
    repo, engine_sha, base_sha, head_sha = _make_isolated_pinned_repo(tmp_path)

    # --- Scenario A: ci-matrix real subprocess with real observation capture (no records_override) ---
    evidence_dir = tmp_path / "selection-evidence"
    evidence_dir.mkdir()
    _write_selection_evidence(
        repo,
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=engine_sha,
        run_id="run-e2e",
        observed_at=EVENT_TIME,
        evidence_dir=evidence_dir,
    )
    ci_proc = subprocess.run(
        [
            sys.executable,
            str(CI_DISCOVER),
            "ci-matrix",
            "--root",
            str(repo),
            "--run",
            "run-e2e",
            "--event",
            "pull_request",
            "--base-ref",
            "main",
            "--event-time",
            str(EVENT_TIME),
            "--evidence-dir",
            str(evidence_dir),
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ci_proc.returncode == 0, (
        f"ci-matrix subprocess failed (rc={ci_proc.returncode}):\n{ci_proc.stderr}\n{ci_proc.stdout}"
    )
    happy_ci = json.loads(ci_proc.stdout)
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

    # --- Scenario C: coordinator-state real subprocess with native dates + role-scoped publication ---
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

    coord_proc = subprocess.run(
        [
            sys.executable,
            str(CI_DISCOVER),
            "coordinator-state",
            "--root",
            str(repo),
            "--run",
            "run-coord",
            "--records",
            str(coord_file),
            "--role",
            "coordinator",
            "--role-mode",
            "may_read",
            "--knowledge-time",
            EVENT_ISO,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert coord_proc.returncode == 0, (
        f"coordinator-state subprocess failed (rc={coord_proc.returncode}):\n{coord_proc.stderr}\n{coord_proc.stdout}"
    )
    coord_state = json.loads(coord_proc.stdout)
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
    denied_proc = subprocess.run(
        [
            sys.executable,
            str(CI_DISCOVER),
            "coordinator-state",
            "--root",
            str(repo),
            "--run",
            "run-coord",
            "--records",
            str(coord_file),
            "--role",
            "unprivileged",
            "--role-mode",
            "may_read",
            "--knowledge-time",
            EVENT_ISO,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied_proc.returncode == 0, (
        f"coordinator-state unprivileged subprocess failed (rc={denied_proc.returncode}):\n{denied_proc.stderr}"
    )
    denied_state = json.loads(denied_proc.stdout)
    assert denied_state["source"] == "pack", (
        f"expected verified pack publication for unprivileged role, got {denied_state}"
    )
    assert denied_state["safe_mode"] is False
    assert denied_state["findings"] == []
    assert denied_state["ready"] == []
    assert denied_state["waiting"] == []
    assert denied_state["stuck"] == []
    assert denied_state["claim_release_plan"] == []
    assert denied_state["claim_held"] == []
