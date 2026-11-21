"""Strict red tests for manifest identity boundaries and endpoint manifest capture in `loop/ci_discover.py`.

Covers decisions/build-reconciliation.md:
1. Coordinator state verification (`evaluate_coordinator_state` / `_verify_publication_on_pinned_engine`)
   must reject any checker-valid manifest that carries a non-null `variant` or `proposal`, or whose
   `pack` or `definition_sha256` does not match the pinned `build/` pack, failing closed to
   `safe_mode` (`safe_mode_reason == "invalid-publication"`, `assign_new_tasks is False`).
2. Endpoint manifest capture (`_capture_endpoint_manifests` / `discover_ci_matrix`) must fail closed
   (selecting the full suite matrix) when a component manifest (`pyproject.toml` / `package.json`) is
   malformed TOML/JSON or a Git symlink (`120000`) at an endpoint instead of silently dropping edges.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BUILD_DIR = ROOT / "build"

COMMIT_TIME = 1_700_000_000
EVENT_TIME = 1_810_000_200
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


def _seed_pinned_engine_tree(dst: Path) -> None:
    """Extract the repository's real pinned engine commit from `build/engine-pin.yaml` into `dst`."""
    from loop.build_pinned_runner import read_engine_pin
    import loop.ci_discover as ci_discover

    pinned_sha = read_engine_pin(ROOT / "build" / "engine-pin.yaml")
    available: list[str] = []
    for rel in ci_discover._PINNED_ARCHIVE_PATHS:
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"{pinned_sha}:{rel}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            available.append(rel)
    archive_bytes = subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "archive", pinned_sha, "--", *available],
        cwd=ROOT,
        stderr=subprocess.PIPE,
    )
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
        tar.extractall(dst, filter="data")


def _create_synthetic_components(repo: Path) -> None:
    pkg_names = {
        "alpha": "rezono-alpha",
        "beta": "rezono-beta",
        "gamma": "rezono-gamma",
        "spare": "rezono-spare",
    }
    deps = {
        "alpha": [],
        "beta": ["rezono-alpha"],
        "gamma": [],
        "spare": [],
    }
    for name in SUITES:
        comp_dir = repo / name
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "pyproject.toml").write_text(
            f'[project]\nname = {json.dumps(pkg_names[name])}\nversion = "0.1.0"\n'
            f"dependencies = {json.dumps(deps[name])}\n",
            encoding="utf-8",
            newline="\n",
        )
        (comp_dir / "test_unit.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8", newline="\n")


def _make_pinned_repo_base(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a 2-commit repo with pinned engine snapshot at commit 1 and synthetic suites at commit 2 (`origin/main`)."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _seed_pinned_engine_tree(repo)
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
    (repo / "build" / "engine-pin.yaml").write_text(f"engine_sha: {engine_sha}\n", encoding="utf-8", newline="\n")
    _create_synthetic_components(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "Seed synthetic candidate repository", env=_commit_env(COMMIT_TIME))
    base_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)
    return repo, engine_sha, base_sha


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
    changed_path: str,
    owner_suite: str,
    evidence_dir: Path,
    skip_head_beta_manifest: bool = False,
) -> str:
    """Write independent admitted completeness evidence for one changed path and return its receipt ID."""
    from rezono_canon import canonical_bytes, canonical_sha256

    pkg_to_folder = {
        "rezono-alpha": "alpha",
        "rezono-beta": "beta",
        "rezono-gamma": "gamma",
        "rezono-spare": "spare",
    }
    registry = {
        "paths": {changed_path: {"direct": [], "transitive": [owner_suite]}},
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
        [owner_suite],
    )
    add_member(
        ["path-reader", changed_path, "transitive", owner_suite],
        {"revision": engine_sha, "path": AUTHORITY_PATH},
        [owner_suite],
    )
    add_member(["file-dependencies"], {"revision": engine_sha, "path": AUTHORITY_PATH}, [])

    for revision in (base_sha, head_sha):
        for suite in SUITES:
            manifest_rel = f"{suite}/pyproject.toml"
            if revision == head_sha and suite == "beta" and skip_head_beta_manifest:
                continue
            blob = _git(repo, "rev-parse", f"{revision}:{manifest_rel}")
            raw_text = _git(repo, "show", f"{revision}:{manifest_rel}")
            try:
                project = tomllib.loads(raw_text).get("project", {})
            except tomllib.TOMLDecodeError:
                project = {}
            origin = {"revision": revision, "path": manifest_rel, "mode": "100644", "blob": blob}
            add_member(["manifest", revision, manifest_rel], origin, [project])
            dep_folders = [pkg_to_folder[dep] for dep in project.get("dependencies", []) if dep in pkg_to_folder]
            add_member(["manifest-dependencies", revision, manifest_rel], origin, dep_folders)
            for folder in dep_folders:
                add_member(["manifest-dependency", revision, manifest_rel, folder], origin, [folder])
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
    context_doc = {"completeness": [protected_context], "rounds": []}
    index_doc = {"completeness_receipts": [_archived_ref("observations/submitted/receipt.json", receipt)], "rounds": []}
    (evidence_dir / "context.json").write_bytes(canonical_bytes(context_doc))
    (evidence_dir / "index.json").write_bytes(canonical_bytes(index_doc))
    return receipt_id


def _build_coordinator_records(
    *,
    base_sha: str,
    head_sha: str,
    engine_sha: str,
    run_id: str,
    observed_at: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    exp_gen = hashlib.sha1(b"task/expired").hexdigest()
    records: dict[str, Any] = {
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
        "loop_step": [{"id": "lang"}],
        "build_task": [
            {"id": "task-lang", "run": run_id, "step": "lang", "track": "language", "source": "board"},
        ],
        "reference_date": [{
            "id": "policy-day",
            "title": "Observed reference date",
            "day": 20270511,
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
        "build_claim": [{
            "id": "task/expired",
            "run": run_id,
            "branch": "task/expired",
            "generation": exp_gen,
            "observed_at": observed_at,
            "source": "ref-listing",
        }],
        "build_claim_activity": [{
            "id": "push-expired",
            "claim": "task/expired",
            "after": exp_gen,
            "pushed_at": observed_at - LEASE_SECONDS,
            "source": "push-activity",
        }],
        "build_claim_pull_reading": [{
            "id": "pr-expired",
            "claim": "task/expired",
            "observed_at": observed_at,
            "state": "none",
            "source": "pull-query",
            "receipt": "rcpt-coord",
        }],
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


def _publish_real_build_archive(
    tmp_path: Path,
    *,
    repo: Path,
    base_sha: str,
    head_sha: str,
    engine_sha: str,
    run_id: str,
) -> tuple[Path, Path, dict[str, Any]]:
    """Publish a real checker-valid pinned `build/` epoch on the pinned engine and return (manifest_path, archive_dir, manifest)."""
    import sys
    import loop.ci_discover as ci_discover

    pinned_work = tmp_path / "pinned-build-work"
    pinned_work.mkdir(parents=True, exist_ok=True)
    ci_discover._extract_pinned_engine(repo, engine_sha, pinned_work)

    records, sidecar = _build_coordinator_records(
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=engine_sha,
        run_id=run_id,
        observed_at=EVENT_TIME,
    )
    facts_dir = pinned_work / "build" / "facts"
    facts_dir.mkdir(exist_ok=True)
    (facts_dir / "z_coord_case.yaml").write_text(
        yaml.safe_dump(records, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (facts_dir / "z_coord_case.sources.yaml").write_text(
        yaml.safe_dump(sidecar, sort_keys=False), encoding="utf-8", newline="\n"
    )

    archive_dir = tmp_path / "archive"
    manifest_path = tmp_path / "manifest-valid.json"
    helper_script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "pinned = Path(sys.argv[1]).resolve()\n"
        "archive_dir = Path(sys.argv[2]).resolve()\n"
        "manifest_path = Path(sys.argv[3]).resolve()\n"
        "engine_sha = sys.argv[4]\n"
        "kt = sys.argv[5]\n"
        "sys.meta_path[:] = [f for f in sys.meta_path if 'editable' not in type(f).__name__.lower() "
        "and 'editable' not in getattr(type(f), '__module__', '').lower()]\n"
        "sys.path[:0] = [str(pinned / '_pinned_meta')] + [str(pinned / r) for r in "
        "('canon', 'compiler', 'checker', 'edge/publisher', 'admission', 'publication', 'contracts/python')]\n"
        "from rezono_publisher import batch, publish, store\n"
        "epoch = batch.epoch(pinned / 'build', epoch=1, knowledge_time=kt, sources=[('rules', engine_sha)])\n"
        "manifest = publish.publish(epoch, store.FileStore(archive_dir), {'reader': 'complete'})\n"
        "if not any(c.get('name') == 'rezono:schema' for c in manifest.get('checks', [])):\n"
        "    manifest = {**manifest, 'checks': [*manifest.get('checks', []), "
        "{'name': 'rezono:schema', 'status': 'green', 'violations': 0}]}\n"
        "manifest_path.write_text(json.dumps(manifest, indent=2) + '\\n', encoding='utf-8')\n"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-E",
            "-P",
            "-c",
            helper_script,
            str(pinned_work),
            str(archive_dir),
            str(manifest_path),
            engine_sha,
            EVENT_ISO,
        ],
        cwd=pinned_work,
        env=ci_discover._scrubbed_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"failed to publish pinned build archive:\n{proc.stderr}\n{proc.stdout}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest_path, archive_dir, manifest


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/build-reconciliation.md: evaluate_coordinator_state / "
        "_verify_publication_on_pinned_engine must reject checker-valid manifests carrying a non-null "
        "`variant` or `proposal`, or whose `pack` or `definition_sha256` does not match the pinned "
        "`build/` pack, falling back to `invalid-publication` safe mode with assign_new_tasks=False."
    ),
)
def test_coordinator_state_rejects_variant_proposal_and_wrong_pack_manifests(tmp_path: Path):
    import loop.ci_discover as ci_discover

    repo, engine_sha, base_sha = _make_pinned_repo_base(tmp_path)
    (repo / "alpha" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Candidate change", env=_commit_env(COMMIT_TIME))
    head_sha = _git(repo, "rev-parse", "HEAD")

    run_id = "run-manifest-boundary"
    valid_manifest_path, archive_dir, valid_manifest = _publish_real_build_archive(
        tmp_path,
        repo=repo,
        base_sha=base_sha,
        head_sha=head_sha,
        engine_sha=engine_sha,
        run_id=run_id,
    )

    # Control: the unmodified main manifest for pinned `build/` verifies green and enables task assignment.
    control = ci_discover.evaluate_coordinator_state(
        root=repo,
        run_id=run_id,
        manifest_path=valid_manifest_path,
        archive_dir=archive_dir,
        role="reader",
        role_mode="complete",
        knowledge_time=EVENT_ISO,
    )
    assert control["source"] == "pack", f"valid control manifest must pass verification: {control!r}"
    assert control["safe_mode"] is False
    assert control["assign_new_tasks"] is True
    assert control["ready"] == [{"task": "task-lang", "reason": "lang"}]

    expected_safe = {
        "run": run_id,
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
            "run": run_id,
            "surface": "coordinator",
            "reason": "invalid-publication",
        }],
    }

    tampered_cases = [
        (
            "variant-manifest",
            {
                **valid_manifest,
                "id": "v-whatif-00-1",
                "variant": {
                    "sweep": "whatif",
                    "index": 0,
                    "kind": "build_run",
                    "key": run_id,
                    "slot": "event",
                    "value": "push",
                },
            },
        ),
        (
            "proposal-manifest",
            {
                **valid_manifest,
                "id": "p-draft-1",
                "proposal": "draft",
            },
        ),
        (
            "wrong-pack-name",
            {
                **valid_manifest,
                "pack": "other-pack",
            },
        ),
        (
            "wrong-definition-sha256",
            {
                **valid_manifest,
                "definition_sha256": "0" * 64,
            },
        ),
    ]

    for label, mutated in tampered_cases:
        bad_path = tmp_path / f"manifest-{label}.json"
        bad_path.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8", newline="\n")
        got = ci_discover.evaluate_coordinator_state(
            root=repo,
            run_id=run_id,
            manifest_path=bad_path,
            archive_dir=archive_dir,
            role="reader",
            role_mode="complete",
            knowledge_time=EVENT_ISO,
        )
        assert got == expected_safe, f"{label} must be rejected into invalid-publication safe_mode; got {got!r}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/build-reconciliation.md: _capture_endpoint_manifests / discover_ci_matrix must "
        "fail closed to full suite selection when an endpoint manifest is malformed TOML or a Git "
        "symlink instead of silently dropping head dependency edges."
    ),
)
def test_endpoint_manifest_capture_fails_closed_on_malformed_or_symlinked_manifest(tmp_path: Path):
    import loop.ci_discover as ci_discover
    from scripts.components import Component

    # 1. Control: on a clean valid commit, capture_ci_records preserves both base-beta and head-beta
    #    dependency edges on alpha without error.
    ctrl_repo, ctrl_engine, ctrl_base = _make_pinned_repo_base(tmp_path / "control")
    (ctrl_repo / "alpha" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(ctrl_repo, "add", ".")
    _git(ctrl_repo, "commit", "-qm", "Clean alpha change", env=_commit_env(COMMIT_TIME))
    ctrl_head = _git(ctrl_repo, "rev-parse", "HEAD")
    ctrl_records, _ = ci_discover.capture_ci_records(
        root=ctrl_repo,
        run_id="run-ctrl",
        build_event="pull_request",
        base_sha=ctrl_base,
        head_sha=ctrl_head,
        engine_sha=ctrl_engine,
        observed_at=EVENT_TIME,
        components=[Component(folder=s, kind="python") for s in SUITES],
        changed_paths=["alpha/engine.py"],
    )
    ctrl_edges = {
        (dep["manifest"], dep["dependency"], dep["consumer"])
        for dep in ctrl_records["build_dependency"]
    }
    assert {("base-beta", "alpha", "beta"), ("head-beta", "alpha", "beta")} <= ctrl_edges

    # 2. Malformed TOML on head (`beta/pyproject.toml` valid on base depending on rezono-alpha, broken on head):
    #    discover_ci_matrix must fail closed and select the full suite universe ["alpha", "beta", "gamma", "spare"].
    bad_repo, bad_engine, bad_base = _make_pinned_repo_base(tmp_path / "malformed")
    (bad_repo / "beta" / "pyproject.toml").write_text("[project\nbroken\n", encoding="utf-8", newline="\n")
    _git(bad_repo, "add", "beta/pyproject.toml")
    _git(bad_repo, "commit", "-qm", "Break beta pyproject.toml", env=_commit_env(COMMIT_TIME))
    bad_head = _git(bad_repo, "rev-parse", "HEAD")
    bad_ev = tmp_path / "malformed-evidence"
    _write_selection_evidence(
        bad_repo,
        base_sha=bad_base,
        head_sha=bad_head,
        engine_sha=bad_engine,
        run_id="run-malformed",
        observed_at=EVENT_TIME,
        changed_path="beta/pyproject.toml",
        owner_suite="beta",
        evidence_dir=bad_ev,
    )
    bad_res = ci_discover.discover_ci_matrix(
        root=bad_repo,
        run_id="run-malformed",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
        evidence_dir=bad_ev,
    )
    assert bad_res["outcome"]["use"] == list(SUITES), (
        f"malformed beta/pyproject.toml on head must fail closed to full suite selection {list(SUITES)}; "
        f"got {bad_res['outcome']!r}"
    )
    assert sorted({item["folder"] for item in bad_res["matrix"]["python"]}) == list(SUITES)

    # 3. Symlinked manifest on head (`beta/pyproject.toml` replaced with Git symlink mode 120000):
    #    discover_ci_matrix must fail closed and select the full suite universe ["alpha", "beta", "gamma", "spare"].
    sym_repo, sym_engine, sym_base = _make_pinned_repo_base(tmp_path / "symlink")
    link_target_sha = subprocess.check_output(
        ["git", "hash-object", "-w", "--stdin"],
        input=b"../alpha/pyproject.toml",
        cwd=sym_repo,
        stderr=subprocess.PIPE,
    ).decode("ascii").strip()
    _git(sym_repo, "update-index", "--replace", "--cacheinfo", f"120000,{link_target_sha},beta/pyproject.toml")
    _git(sym_repo, "commit", "-qm", "Replace beta/pyproject.toml with symlink", env=_commit_env(COMMIT_TIME))
    sym_head = _git(sym_repo, "rev-parse", "HEAD")
    sym_ev = tmp_path / "symlink-evidence"
    _write_selection_evidence(
        sym_repo,
        base_sha=sym_base,
        head_sha=sym_head,
        engine_sha=sym_engine,
        run_id="run-symlink",
        observed_at=EVENT_TIME,
        changed_path="beta/pyproject.toml",
        owner_suite="beta",
        evidence_dir=sym_ev,
        skip_head_beta_manifest=True,
    )
    sym_res = ci_discover.discover_ci_matrix(
        root=sym_repo,
        run_id="run-symlink",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
        evidence_dir=sym_ev,
    )
    assert sym_res["outcome"]["use"] == list(SUITES), (
        f"symlinked beta/pyproject.toml on head must fail closed to full suite selection {list(SUITES)}; "
        f"got {sym_res['outcome']!r}"
    )
    assert sorted({item["folder"] for item in sym_res["matrix"]["python"]}) == list(SUITES)
