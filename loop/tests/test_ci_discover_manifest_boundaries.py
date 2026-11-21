"""Strict red tests for manifest identity boundaries and endpoint manifest capture in `loop/ci_discover.py`.

Covers decisions/build-reconciliation.md:
1. Coordinator state verification (`evaluate_coordinator_state` / `_verify_publication_on_pinned_engine`)
   must reject any checker-valid manifest that carries a non-null `variant` or `proposal`, or whose
   `pack` or `definition_sha256` does not match the pinned `build/` pack, failing closed to
   `safe_mode` (`safe_mode_reason == "invalid-publication"`, `assign_new_tasks is False`).
2. Endpoint manifest capture (`_capture_endpoint_manifests` / `discover_ci_matrix`) must fail closed
   (selecting the full suite matrix) when a component manifest (`pyproject.toml` / `package.json`) is
   malformed TOML/JSON or a Git symlink (`120000`) at an endpoint instead of silently dropping edges.

Both tests run against the real pinned engine packages archived in a hermetic pinned commit
alongside a minimal pure-YAML `build/` pack, with strict `RuntimeError` guards on clean controls
so an unrelated engine failure can never cause a false XPASS or false XFAIL.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

COMMIT_TIME = 1_700_000_000
EVENT_TIME = 1_810_000_200
EVENT_ISO = "2027-05-11T01:50:00Z"
SUITES = ("alpha", "beta", "gamma", "spare")

_COPY_SKIP = frozenset({"__pycache__", "tests", "fixtures", ".pytest_cache", "node_modules"})
_SKIP_PACK_DIRS = frozenset({"build", "packs", "rezono"})


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


def _write_minimal_build_pack(build_dir: Path) -> None:
    """Write a minimal, pure-YAML `build/` pack supporting both coordinator-state and ci-matrix selection."""
    for sub in ("schema", "rules", "facts", "labels", "messages"):
        (build_dir / sub).mkdir(parents=True, exist_ok=True)

    (build_dir / "pack.yaml").write_text(
        "name: build-selection\nversion: 0.1.0\ndefault_language: en\nimports: []\n",
        encoding="utf-8",
        newline="\n",
    )
    (build_dir / "channels.yaml").write_text(
        "kinds:\n"
        "  - {kind: build_run, shape: pill}\n"
        "  - {kind: build_component, shape: pill}\n"
        "  - {kind: build_manifest, shape: pill}\n"
        "  - {kind: build_test_file, shape: pill}\n"
        "  - {kind: build_dependency, shape: pill}\n"
        "  - {kind: build_path, shape: pill}\n"
        "  - {kind: build_path_reader, shape: pill}\n"
        "  - {kind: build_task, shape: pill}\n"
        "  - {kind: build_claim, shape: pill}\n",
        encoding="utf-8",
        newline="\n",
    )
    (build_dir / "schema" / "build.yaml").write_text(
        """\
id: https://rezono.example/build-selection/schema
name: build_selection
prefixes:
  linkml: https://w3id.org/linkml/
imports:
  - linkml:types
default_range: string
annotations:
  layer: facts
classes:
  BuildRun:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      event: {required: true}
      base_sha: {required: true}
      head_sha: {required: true}
      engine_sha: {required: true}
      observed_at: {range: integer, required: true}
  BuildComponent:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      run: {range: BuildRun, required: true}
      folder: {required: true}
      kind: {required: true}
  BuildManifest:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      component: {range: BuildComponent, required: true}
      path: {required: true}
      revision: {required: true}
      blob: {required: true}
  BuildTestFile:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      component: {range: BuildComponent, required: true}
      path: {required: true}
  BuildDependency:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      dependency: {range: BuildComponent, required: true}
      consumer: {range: BuildComponent, required: true}
      kind: {required: true}
      manifest: {range: BuildManifest}
      source: {required: true}
  BuildPath:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      run: {range: BuildRun, required: true}
      path: {required: true}
      coverage: {required: true}
  BuildPathReader:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      path: {range: BuildPath, required: true}
      component: {range: BuildComponent, required: true}
      kind: {required: true}
      source: {required: true}
  BuildTask:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      run: {range: BuildRun, required: true}
      step: {required: true}
      state: {required: true}
  BuildClaim:
    annotations: {world: closed}
    attributes:
      id: {identifier: true, required: true}
      run: {range: BuildRun, required: true}
      generation: {required: true}
      status: {required: true}
""",
        encoding="utf-8",
        newline="\n",
    )
    (build_dir / "rules" / "build.dl").write_text(
        """\
.decl build_affected(run: symbol, component: symbol, path: symbol)
.decl build_selected_job(run: symbol, component: symbol, reason: symbol)
.decl build_full_selection(run: symbol, reason: symbol)
.decl build_task_ready(run: symbol, task: symbol, reason: symbol)
.decl build_task_waiting(run: symbol, task: symbol, reason: symbol)
.decl build_task_stuck(run: symbol, task: symbol, reason: symbol)
.decl build_claim_release_plan(run: symbol, claim: symbol, generation: symbol, reason: symbol)
.decl build_claim_held(run: symbol, claim: symbol, reason: symbol)

build_full_selection(run, path) :- build_path__run(path, run), build_path__coverage(path, "unknown").
build_affected(run, component, path) :- build_path__run(path, run), build_path__coverage(path, "mapped"),
    build_path_reader__path(reader, path), build_path_reader__component(reader, component).
build_affected(run, consumer, path) :- build_affected(run, dep, path),
    build_dependency__dependency(edge, dep), build_dependency__consumer(edge, consumer),
    build_component__run(dep, run), build_component__run(consumer, run).
build_selected_job(run, component, path) :- build_affected(run, component, path).
build_selected_job(run, component, reason) :- build_full_selection(run, reason), build_component__run(component, run).

build_task_ready(run, task, step) :- build_task__run(task, run), build_task__step(task, step), build_task__state(task, "ready").
build_task_waiting(run, task, step) :- build_task__run(task, run), build_task__step(task, step), build_task__state(task, "waiting").
build_task_stuck(run, task, step) :- build_task__run(task, run), build_task__step(task, step), build_task__state(task, "stuck").
build_claim_release_plan(run, claim, gen, "lease-ended") :- build_claim__run(claim, run),
    build_claim__generation(claim, gen), build_claim__status(claim, "expired").
build_claim_held(run, claim, "active") :- build_claim__run(claim, run), build_claim__status(claim, "active").

.output build_selected_job
.output build_full_selection
.output build_task_ready
.output build_task_waiting
.output build_task_stuck
.output build_claim_release_plan
.output build_claim_held
""",
        encoding="utf-8",
        newline="\n",
    )
    (build_dir / "labels" / "en.yaml").write_text(
        "build_run: run\n"
        "build_component: component\n"
        "build_manifest: manifest\n"
        "build_test_file: test file\n"
        "build_dependency: dependency\n"
        "build_path: path\n"
        "build_path_reader: path reader\n"
        "build_task: task\n"
        "build_claim: claim\n",
        encoding="utf-8",
        newline="\n",
    )
    (build_dir / "messages" / "en.mf2").write_text(
        "@locale en\n---\n"
        "arrow.total = {{Every {$kind} has exactly one {$arrow}.}}\n"
        "arrow.partial = {{Every {$kind} has at most one {$arrow}.}}\n"
        "attribute.total = {{Every {$kind} has exactly one {$attribute}.}}\n"
        "attribute.partial = {{Every {$kind} has at most one {$attribute}.}}\n"
        "is_a = {{Every {$kind} is a {$parent}.}}\n"
        "unique_key = {{{$key} belongs to at most one {$kind}.}}\n"
        "path_equation = {{For every {$kind}: {$equation}.}}\n",
        encoding="utf-8",
        newline="\n",
    )


def _seed_pinned_engine_tree(dst: Path) -> None:
    """Copy the real engine packages from ROOT alongside the minimal pure-YAML `build/` pack."""
    import loop.ci_discover as ci_discover

    def _ignore(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name in _COPY_SKIP]

    for rel in ci_discover._PINNED_ARCHIVE_PATHS:
        if rel in _SKIP_PACK_DIRS:
            continue
        src = ROOT / rel
        if src.is_dir():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, target, ignore=_ignore)
    _write_minimal_build_pack(dst / "build")


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
        }],
        "build_task": [
            {"id": "task-lang", "run": run_id, "step": "lang", "state": "ready"},
        ],
        "build_claim": [{
            "id": "task/expired",
            "run": run_id,
            "generation": exp_gen,
            "status": "expired",
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
        "py_dirs = json.loads(sys.argv[6])\n"
        "sys.meta_path[:] = [f for f in sys.meta_path if 'editable' not in type(f).__name__.lower() "
        "and 'editable' not in getattr(type(f), '__module__', '').lower()]\n"
        "sys.path[:0] = [str(pinned / '_pinned_meta')] + [str(pinned / r) for r in py_dirs]\n"
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
            json.dumps(list(ci_discover._PINNED_PYTHON_DIRS)),
        ],
        cwd=pinned_work,
        env=ci_discover._scrubbed_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"failed to publish pinned build archive:\n{proc.stderr}\n{proc.stdout}")
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

    # Control: unmodified main manifest for pinned `build/` verifies green and enables task assignment.
    # Raise RuntimeError (not AssertionError) if the control fails so setup bugs can never mask as XFAIL.
    control = ci_discover.evaluate_coordinator_state(
        root=repo,
        run_id=run_id,
        manifest_path=valid_manifest_path,
        archive_dir=archive_dir,
        role="reader",
        role_mode="complete",
        knowledge_time=EVENT_ISO,
    )
    if (
        control.get("source") != "pack"
        or control.get("safe_mode") is not False
        or control.get("assign_new_tasks") is not True
        or control.get("ready") != [{"task": "task-lang", "reason": "lang"}]
    ):
        raise RuntimeError(f"valid control manifest must pass verification: {control!r}")

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

    # 1. Control: on a clean valid commit touching alpha/engine.py, discover_ci_matrix runs the pinned
    #    build pack cleanly (source == "pack", safe_mode is False) and narrows selection to ["alpha", "beta"].
    #    Raise RuntimeError on control failure so an unrelated engine-failure safe_mode can never cause false XPASS.
    ctrl_repo, _, _ = _make_pinned_repo_base(tmp_path / "control")
    (ctrl_repo / "alpha" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    _git(ctrl_repo, "add", ".")
    _git(ctrl_repo, "commit", "-qm", "Clean alpha change", env=_commit_env(COMMIT_TIME))
    ctrl_res = ci_discover.discover_ci_matrix(
        root=ctrl_repo,
        run_id="run-ctrl",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
    )
    if (
        ctrl_res.get("engine_error") is not None
        or ctrl_res["outcome"].get("source") != "pack"
        or ctrl_res["outcome"].get("safe_mode") is not False
        or ctrl_res["outcome"].get("use") != ["alpha", "beta"]
    ):
        raise RuntimeError(
            f"clean control must narrow selection to ['alpha', 'beta'] without safe_mode; "
            f"got engine_error={ctrl_res.get('engine_error')!r}, outcome={ctrl_res['outcome']!r}"
        )

    # 2. Malformed TOML on head (`beta/pyproject.toml` valid on base depending on rezono-alpha, broken on head):
    #    discover_ci_matrix must fail closed and select the full suite universe ["alpha", "beta", "gamma", "spare"].
    bad_repo, _, _ = _make_pinned_repo_base(tmp_path / "malformed")
    (bad_repo / "beta" / "pyproject.toml").write_text("[project\nbroken\n", encoding="utf-8", newline="\n")
    _git(bad_repo, "add", "beta/pyproject.toml")
    _git(bad_repo, "commit", "-qm", "Break beta pyproject.toml", env=_commit_env(COMMIT_TIME))
    bad_res = ci_discover.discover_ci_matrix(
        root=bad_repo,
        run_id="run-malformed",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
    )
    assert bad_res["outcome"]["use"] == list(SUITES), (
        f"malformed beta/pyproject.toml on head must fail closed to full suite selection {list(SUITES)}; "
        f"got {bad_res['outcome']!r}"
    )
    assert sorted({item["folder"] for item in bad_res["matrix"]["python"]}) == list(SUITES)

    # 3. Symlinked manifest on head (`beta/pyproject.toml` replaced with Git symlink mode 120000 via index):
    #    discover_ci_matrix must fail closed and select the full suite universe ["alpha", "beta", "gamma", "spare"].
    sym_repo, _, _ = _make_pinned_repo_base(tmp_path / "symlink")
    link_target_sha = subprocess.check_output(
        ["git", "hash-object", "-w", "--stdin"],
        input=b"../alpha/pyproject.toml",
        cwd=sym_repo,
        stderr=subprocess.PIPE,
    ).decode("ascii").strip()
    _git(sym_repo, "update-index", "--replace", "--cacheinfo", f"120000,{link_target_sha},beta/pyproject.toml")
    _git(sym_repo, "commit", "-qm", "Replace beta/pyproject.toml with symlink", env=_commit_env(COMMIT_TIME))
    sym_res = ci_discover.discover_ci_matrix(
        root=sym_repo,
        run_id="run-symlink",
        event_name="pull_request",
        base_ref="main",
        event_time=EVENT_TIME,
    )
    assert sym_res["outcome"]["use"] == list(SUITES), (
        f"symlinked beta/pyproject.toml on head must fail closed to full suite selection {list(SUITES)}; "
        f"got {sym_res['outcome']!r}"
    )
    assert sorted({item["folder"] for item in sym_res["matrix"]["python"]}) == list(SUITES)
