"""CI executes `build/` on the pinned earlier main engine and production entrypoints wire the cutover
readers (`decisions/build-reconciliation.md`).

Verifies that:
1. `.github/workflows/ci.yml` executes `build/` on the pinned engine commit read from
   `build/engine-pin.yaml` and derives CI test selection from verified `build/` publications
   instead of invoking `components.py ci-matrix`.
2. Non-test production entrypoints (not merely unit tests) wire `loop/build_cutover.py`,
   `loop/build_coordinator_reader.py`, and `loop/build_pinned_runner.py`.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import textwrap

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
ENGINE_PIN = ROOT / "build" / "engine-pin.yaml"
SHA40 = re.compile(r"^[0-9a-f]{40}$")

PRODUCTION_ROOTS = ("loop", "scripts", "run", "edge", "build")
LIBRARY_MODULES = {
    "loop/build_cutover.py",
    "loop/build_coordinator_reader.py",
    "loop/build_pinned_runner.py",
}


def _executable_shell_lines(script: str) -> list[str]:
    """Return non-empty, non-comment shell lines from a workflow step `run:` block."""
    out: list[str] = []
    for raw in script.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def _is_production_python(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel in LIBRARY_MODULES:
        return False
    parts = [p.lower() for p in path.relative_to(ROOT).parts]
    if any(p in {"test", "tests", "fixture", "fixtures", "__pycache__"} for p in parts[:-1]):
        return False
    name = path.name.lower()
    return not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


def _production_python_files() -> list[Path]:
    found: list[Path] = []
    for folder in PRODUCTION_ROOTS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if _is_production_python(path):
                found.append(path)
    return found


def _module_imports_and_calls(path: Path) -> tuple[dict[str, str], set[str], set[str]]:
    """Inspect a Python module's AST for imports, direct/attribute call names, and string literals.

    Returns:
      - `bindings`: local identifier -> imported dotted target (e.g. `select_suites` -> `loop.build_cutover.select_suites`)
      - `called_targets`: resolved dotted targets actually invoked in an `ast.Call`
      - `string_literals`: all constant string literals in the module
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bindings[local] = alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                bindings[local] = f"{mod}.{alias.name}" if mod else alias.name

    called_targets: set[str] = set()
    string_literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.add(node.value)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in bindings:
                called_targets.add(bindings[func.id])
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                base = bindings.get(func.value.id)
                if base:
                    called_targets.add(f"{base}.{func.attr}")
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
            ):
                base = bindings.get(func.value.value.id)
                if base:
                    called_targets.add(f"{base}.{func.value.attr}.{func.attr}")
    return bindings, called_targets, string_literals


def _matches_target(called: set[str], module_stem: str, func_name: str) -> bool:
    """Whether `called` contains a real invocation of `<module_stem>.<func_name>`."""
    suffixes = (f"{module_stem}.{func_name}", f"loop.{module_stem}.{func_name}")
    return any(target == s or target.endswith(f".{s}") for target in called for s in suffixes)


def _discover_invoked_python_files(shell_lines: list[str]) -> set[Path]:
    """Collect local production Python files invoked directly from `discover` shell lines,
    plus their transitive local imports inside `scripts/` and `loop/`."""
    queue: list[Path] = []
    seen: set[Path] = set()
    script_re = re.compile(r"\b((?:scripts|loop|build|run)/[A-Za-z0-9_./-]+\.py)\b")
    module_re = re.compile(r"\bpython3?\b[^\n]*?\s-m\s+((?:scripts|loop)\.[A-Za-z0-9_.]+)")

    for line in shell_lines:
        for match in script_re.finditer(line):
            candidate = ROOT / match.group(1)
            if candidate.is_file() and _is_production_python(candidate):
                queue.append(candidate)
        for match in module_re.finditer(line):
            rel = Path(*match.group(1).split(".")).with_suffix(".py")
            candidate = ROOT / rel
            if candidate.is_file() and _is_production_python(candidate):
                queue.append(candidate)

    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        bindings, _, _ = _module_imports_and_calls(current)
        for target in bindings.values():
            parts = target.split(".")
            for length in range(len(parts), 0, -1):
                prefix = parts[:length]
                candidates = [
                    ROOT / Path(*prefix).with_suffix(".py"),
                    ROOT / "scripts" / Path(*prefix).with_suffix(".py"),
                    ROOT / "loop" / Path(*prefix).with_suffix(".py"),
                ]
                for candidate in candidates:
                    if candidate.is_file() and _is_production_python(candidate) and candidate not in seen:
                        queue.append(candidate)
                        break
    return seen


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=CI Discover Fixture",
            "-c",
            "user.email=ci-discover-fixture@example.org",
            *args,
        ],
        cwd=repo,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def _prepare_fixture_repo(tmp_path: Path, pinned_sha: str) -> tuple[Path, str, str]:
    """Create a temporary Git fixture repo sharing history with ROOT and one candidate commit."""
    fixture = tmp_path / "fixture"
    subprocess.check_call(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(ROOT), str(fixture)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    _git(fixture, "checkout", "--quiet", "--force", "HEAD")

    # Overlay any local working-tree modifications from ROOT so uncommitted edits are exercised too.
    status_raw = subprocess.check_output(
        ["git", "status", "--porcelain", "-z"],
        cwd=ROOT,
        text=True,
    )
    skip_top = {".git", ".claude", ".build-base", "node_modules", "__pycache__"}
    for entry in status_raw.split("\0"):
        if not entry:
            continue
        code = entry[:2]
        rel_path = entry[3:]
        if not rel_path or rel_path.split("/", 1)[0] in skip_top:
            continue
        src = ROOT / rel_path
        dst = fixture / rel_path
        if "D" in code and not src.exists():
            if dst.exists():
                dst.unlink()
        elif src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    if _git(fixture, "status", "--porcelain"):
        _git(fixture, "add", "-A")
        _git(fixture, "commit", "-qm", "Sync candidate working tree into fixture")

    base_sha = _git(fixture, "rev-parse", "HEAD")
    _git(fixture, "update-ref", "refs/remotes/origin/main", base_sha)
    _git(fixture, "checkout", "-q", "-b", "fixture/pinned-engine-change")

    target = fixture / "fixture-candidate-change.txt"
    target.write_text("fixture candidate change\n", encoding="utf-8")
    _git(fixture, "add", "fixture-candidate-change.txt")
    _git(fixture, "commit", "-qm", "Fixture candidate change")
    head_sha = _git(fixture, "rev-parse", "HEAD")

    assert pinned_sha != head_sha, "fixture candidate commit must differ from pinned_sha"
    _git(fixture, "merge-base", "--is-ancestor", pinned_sha, "refs/remotes/origin/main")
    return fixture, base_sha, head_sha


def _write_discover_tracer(trace_dir: Path) -> None:
    """Install a read-only sitecustomize hook that records pinned-runner and cutover calls."""
    trace_dir.mkdir(parents=True, exist_ok=True)
    hook = textwrap.dedent(
        """\
        import functools
        import importlib.abc
        import json
        import os
        import sys

        _TRACE_PATH = os.environ.get("REZONO_DISCOVER_TRACE")
        _TARGETS = {"loop.build_pinned_runner", "loop.build_cutover"}


        def _record(event):
            if not _TRACE_PATH:
                return
            with open(_TRACE_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, sort_keys=True) + "\\n")


        def _wrap_module(fullname, module):
            if getattr(module, "_rezono_discover_traced", False):
                return
            module._rezono_discover_traced = True
            if fullname == "loop.build_pinned_runner":
                orig_read = module.read_engine_pin
                orig_validate = module.validate_engine_pin

                @functools.wraps(orig_read)
                def traced_read(*args, **kwargs):
                    result = orig_read(*args, **kwargs)
                    _record({"fn": "read_engine_pin", "result": result})
                    return result

                @functools.wraps(orig_validate)
                def traced_validate(*args, **kwargs):
                    engine_sha = kwargs.get("engine_sha")
                    candidate_sha = kwargs.get("candidate_sha")
                    try:
                        result = orig_validate(*args, **kwargs)
                    except Exception as exc:
                        _record({
                            "fn": "validate_engine_pin",
                            "engine_sha": engine_sha,
                            "candidate_sha": candidate_sha,
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                        raise
                    _record({
                        "fn": "validate_engine_pin",
                        "engine_sha": engine_sha,
                        "candidate_sha": candidate_sha,
                        "ok": True,
                    })
                    return result

                module.read_engine_pin = traced_read
                module.validate_engine_pin = traced_validate
            elif fullname == "loop.build_cutover":
                orig_select = module.select_suites

                @functools.wraps(orig_select)
                def traced_select(*args, **kwargs):
                    result = orig_select(*args, **kwargs)
                    _record({
                        "fn": "select_suites",
                        "engine_error": kwargs.get("engine_error"),
                        "result": result,
                    })
                    return result

                module.select_suites = traced_select


        class _TraceLoader(importlib.abc.Loader):
            def __init__(self, fullname, loader):
                self._fullname = fullname
                self._loader = loader

            def create_module(self, spec):
                if hasattr(self._loader, "create_module"):
                    return self._loader.create_module(spec)
                return None

            def exec_module(self, module):
                self._loader.exec_module(module)
                _wrap_module(self._fullname, module)


        class _TraceFinder(importlib.abc.MetaPathFinder):
            def __init__(self):
                self._active = False

            def find_spec(self, fullname, path, target=None):
                if self._active or fullname not in _TARGETS:
                    return None
                self._active = True
                try:
                    for finder in sys.meta_path:
                        if finder is self:
                            continue
                        if hasattr(finder, "find_spec"):
                            spec = finder.find_spec(fullname, path, target)
                            if spec is not None and spec.loader is not None:
                                spec.loader = _TraceLoader(fullname, spec.loader)
                                return spec
                finally:
                    self._active = False
                return None


        if _TRACE_PATH:
            sys.meta_path.insert(0, _TraceFinder())
        """
    )
    (trace_dir / "sitecustomize.py").write_text(hook, encoding="utf-8")


def _parse_github_output(text: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if "<<" in line and ("=" not in line or line.index("<<") < line.index("=")):
            key, delim = line.split("<<", 1)
            idx += 1
            buf: list[str] = []
            while idx < len(lines) and lines[idx] != delim:
                buf.append(lines[idx])
                idx += 1
            outputs[key.strip()] = "\n".join(buf)
        elif "=" in line:
            key, value = line.split("=", 1)
            outputs[key.strip()] = value
        idx += 1
    return outputs


def _render_step_env(step_env: dict, *, base_sha: str, head_sha: str) -> dict[str, str]:
    values = {
        "github.base_ref": "main",
        "github.head_ref": "fixture/pinned-engine-change",
        "github.sha": head_sha,
        "github.event.pull_request.base.sha": base_sha,
        "github.event.pull_request.head.sha": head_sha,
        "github.event.pull_request.updated_at": "2026-11-21T12:00:00Z",
        "github.event.merge_group.base_sha": "",
        "github.event.merge_group.head_sha": "",
        "github.event.before": "",
    }
    rendered: dict[str, str] = {}
    for key, raw in (step_env or {}).items():
        text = str(raw)
        expr_match = re.fullmatch(r"\$\{\{\s*(.+?)\s*\}\}", text)
        if expr_match:
            chosen = ""
            for branch in expr_match.group(1).split("||"):
                token = branch.strip().strip("'\"")
                val = values.get(token, "")
                if val:
                    chosen = val
                    break
            rendered[str(key)] = chosen
        else:
            rendered[str(key)] = text
    return rendered


def _find_native_bash() -> str | None:
    """Return a native bash executable, avoiding Windows WSL launchers."""
    if os.name != "nt":
        return shutil.which("bash")
    git_bin = shutil.which("git")
    if git_bin:
        git_root = Path(git_bin).resolve().parents[1]
        for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
            found = git_root / rel
            if found.is_file():
                return str(found)
    candidate = shutil.which("bash")
    if candidate:
        lowered = Path(candidate).as_posix().lower()
        if "system32" not in lowered and "windowsapps" not in lowered:
            return candidate
    return None


def _run_discover_matrix_step(
    matrix_step: dict,
    fixture: Path,
    tmp_path: Path,
    *,
    label: str,
    base_sha: str,
    head_sha: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], str, list[dict]]:
    """Execute the workflow's `discover` `matrix` step inside `fixture` and collect its outputs and trace."""
    run_dir = tmp_path / f"run-{label}"
    run_dir.mkdir(parents=True, exist_ok=True)
    gh_output = run_dir / "github_output.txt"
    gh_summary = run_dir / "github_summary.md"
    trace_file = run_dir / "trace.jsonl"
    runner_temp = run_dir / "runner_temp"
    trace_dir = run_dir / "trace_hook"
    bin_dir = run_dir / "bin"
    gh_output.write_text("", encoding="utf-8")
    gh_summary.write_text("", encoding="utf-8")
    trace_file.write_text("", encoding="utf-8")
    runner_temp.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_discover_tracer(trace_dir)

    py_exec = Path(sys.executable).as_posix()
    for shim_name in ("python3", "python"):
        shim = bin_dir / shim_name
        shim.write_text(f"#!/usr/bin/env sh\nexec \"{py_exec}\" \"$@\"\n", encoding="utf-8", newline="\n")
        shim.chmod(0o755)

    env = os.environ.copy()
    env.update(_render_step_env(matrix_step.get("env") or {}, base_sha=base_sha, head_sha=head_sha))
    env.update({
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_BASE_REF": "main",
        "GITHUB_HEAD_REF": "fixture/pinned-engine-change",
        "GITHUB_SHA": head_sha,
        "GITHUB_OUTPUT": str(gh_output),
        "GITHUB_STEP_SUMMARY": str(gh_summary),
        "RUNNER_TEMP": str(runner_temp),
        "REZONO_DISCOVER_TRACE": str(trace_file),
        "PATH": f"{bin_dir}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}",
        "PYTHONPATH": (
            f"{trace_dir}{os.pathsep}{env['PYTHONPATH']}"
            if env.get("PYTHONPATH")
            else str(trace_dir)
        ),
    })

    bash = _find_native_bash()
    if bash is not None:
        script = f"set -euo pipefail\n{matrix_step['run']}\n"
        proc = subprocess.run(
            [bash, "-c", script],
            cwd=fixture,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        lines = _executable_shell_lines(matrix_step["run"])
        assert len(lines) == 1, f"native bash required for multi-line matrix step: {lines!r}"
        argv = shlex.split(lines[0])
        if argv and argv[0] in {"python", "python3"}:
            argv[0] = sys.executable
        proc = subprocess.run(
            argv,
            cwd=fixture,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    outputs = _parse_github_output(gh_output.read_text(encoding="utf-8"))
    summary = gh_summary.read_text(encoding="utf-8")
    events = [
        json.loads(line)
        for line in trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return proc, outputs, summary, events


def _matrix_suite_folders(outputs: dict[str, str]) -> set[str]:
    required_keys = {"python", "has_python", "node", "has_node", "pytest", "has_pytest", "python_editable"}
    missing = sorted(required_keys - set(outputs))
    assert not missing, f"discover matrix step omitted required GITHUB_OUTPUT keys: {missing}"
    py_items = json.loads(outputs["python"])
    node_items = json.loads(outputs["node"])
    pytest_items = json.loads(outputs["pytest"])
    assert isinstance(py_items, list) and isinstance(node_items, list) and isinstance(pytest_items, list)
    assert outputs["has_python"] == ("true" if py_items else "false")
    assert outputs["has_node"] == ("true" if node_items else "false")
    assert outputs["has_pytest"] == ("true" if pytest_items else "false")
    return {item["folder"] for item in py_items + node_items}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: .github/workflows/ci.yml discover matrix step "
           "must execute build/ on the pinned earlier main engine commit read from build/engine-pin.yaml "
           "(invoking Python without `-I` so editable packages and sitecustomize tracing work), "
           "derive the CI matrix via loop/build_cutover.py (select_suites) without calling "
           "components.py ci-matrix, and fail closed into safe_mode selecting every suite when "
           "the pinned engine SHA equals the candidate HEAD SHA.",
)
def test_ci_workflow_executes_build_pack_on_pinned_engine_without_components_ci_matrix(tmp_path):
    from loop.build_pinned_runner import read_engine_pin
    from scripts.components import discover_components

    assert ENGINE_PIN.is_file(), "build/engine-pin.yaml is missing"
    pinned_sha = read_engine_pin(ENGINE_PIN)
    assert SHA40.fullmatch(pinned_sha), f"build/engine-pin.yaml must pin a 40-hex SHA, got {pinned_sha!r}"

    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    discover = workflow["jobs"]["discover"]
    steps = discover["steps"]

    exec_lines: list[str] = []
    for step in steps:
        run_block = step.get("run")
        if isinstance(run_block, str):
            exec_lines.extend(_executable_shell_lines(run_block))

    # 1. CI discover must no longer derive its suite matrix by calling `components.py ci-matrix`.
    legacy_calls = [line for line in exec_lines if re.search(r"components\.py\s+ci-matrix\b", line)]
    assert not legacy_calls, (
        f".github/workflows/ci.yml discover job still calls legacy components.py ci-matrix: {legacy_calls}"
    )

    matrix_step = next((step for step in steps if step.get("id") == "matrix"), None)
    assert isinstance(matrix_step, dict) and isinstance(matrix_step.get("run"), str) and matrix_step["run"].strip(), (
        ".github/workflows/ci.yml discover job must define an executable step with id: matrix"
    )
    assert not re.search(r"\bpython3?\s+(?:-[A-Za-z]*I|--isolated)\b", matrix_step["run"]), (
        ".github/workflows/ci.yml discover matrix step must not pass `-I` / `--isolated` to Python "
        "(it breaks editable package resolution and sitecustomize runtime tracing)"
    )

    # 2. The discover workflow's invoked production scripts must wire read_engine_pin,
    #    validate_engine_pin, and select_suites (no string-literal proxies).
    invoked_scripts = _discover_invoked_python_files(exec_lines)
    all_called: set[str] = set()
    for script in invoked_scripts:
        _, called, _ = _module_imports_and_calls(script)
        all_called.update(called)

    assert _matches_target(all_called, "build_pinned_runner", "read_engine_pin"), (
        ".github/workflows/ci.yml discover path must read build/engine-pin.yaml via "
        "loop.build_pinned_runner.read_engine_pin"
    )
    assert _matches_target(all_called, "build_pinned_runner", "validate_engine_pin"), (
        ".github/workflows/ci.yml discover path must validate the pinned engine commit via "
        "loop.build_pinned_runner.validate_engine_pin"
    )
    assert _matches_target(all_called, "build_cutover", "select_suites"), (
        ".github/workflows/ci.yml discover path must select CI suites from verified build/ "
        "publications via loop.build_cutover.select_suites"
    )

    # 3. Actually execute the discover `matrix` step on a temporary fixture Git repository.
    fixture, base_sha, head_sha = _prepare_fixture_repo(tmp_path, pinned_sha)
    expected_universe = {comp.folder for comp in discover_components(fixture)}
    assert expected_universe, "fixture repository must discover at least one component suite"

    # Case A: valid earlier main pin (`pinned_sha != head_sha`) runs build/ on the pinned engine
    # and emits the CI matrix from `select_suites`.
    proc_ok, out_ok, _summary_ok, events_ok = _run_discover_matrix_step(
        matrix_step,
        fixture,
        tmp_path,
        label="pinned-ok",
        base_sha=base_sha,
        head_sha=head_sha,
    )
    assert proc_ok.returncode == 0, (
        f"discover matrix step failed on valid pinned fixture repo (rc={proc_ok.returncode}):\n"
        f"stdout:\n{proc_ok.stdout}\nstderr:\n{proc_ok.stderr}"
    )
    emitted_ok = _matrix_suite_folders(out_ok)

    read_events = [e for e in events_ok if e["fn"] == "read_engine_pin"]
    assert any(e["result"] == pinned_sha for e in read_events), (
        f"discover matrix step did not read pinned_sha={pinned_sha} from build/engine-pin.yaml: {events_ok}"
    )
    val_events = [e for e in events_ok if e["fn"] == "validate_engine_pin"]
    assert any(
        e["ok"] is True and e["engine_sha"] == pinned_sha and e["candidate_sha"] == head_sha
        for e in val_events
    ), f"discover matrix step did not validate (pinned_sha, head_sha): {val_events}"
    sel_events = [e for e in events_ok if e["fn"] == "select_suites"]
    assert sel_events, f"discover matrix step did not derive the matrix via select_suites: {events_ok}"
    sel_ok = sel_events[-1]["result"]
    assert sel_ok["source"] == "pack" and sel_ok["safe_mode"] is False, (
        f"valid earlier pin must evaluate build/ cleanly without safe_mode, got {sel_ok!r}"
    )
    assert emitted_ok == set(sel_ok["use"]), (
        f"discover matrix output {sorted(emitted_ok)} does not match select_suites use {sorted(sel_ok['use'])}"
    )

    # Case B: equal pin and candidate (`pin_sha == head_sha`) must fail closed into `safe_mode`,
    # selecting every suite in the universe.
    (fixture / "build" / "engine-pin.yaml").write_text(f"engine_sha: {head_sha}\n", encoding="utf-8")
    _git(fixture, "update-ref", "refs/remotes/origin/main", head_sha)

    proc_eq, out_eq, summary_eq, events_eq = _run_discover_matrix_step(
        matrix_step,
        fixture,
        tmp_path,
        label="pin-equals-head",
        base_sha=base_sha,
        head_sha=head_sha,
    )
    assert proc_eq.returncode == 0, (
        f"discover matrix step must fail closed into safe_mode (exit 0 with full matrix) when "
        f"pin_sha == head_sha, got rc={proc_eq.returncode}:\nstdout:\n{proc_eq.stdout}\nstderr:\n{proc_eq.stderr}"
    )
    emitted_eq = _matrix_suite_folders(out_eq)

    val_eq = [e for e in events_eq if e["fn"] == "validate_engine_pin"]
    assert any(
        e["ok"] is False and e["engine_sha"] == head_sha and e["candidate_sha"] == head_sha
        for e in val_eq
    ), f"validate_engine_pin must reject pin_sha == head_sha ({head_sha}), got {val_eq}"
    sel_eq_events = [e for e in events_eq if e["fn"] == "select_suites"]
    assert sel_eq_events, f"pin_sha == head_sha must route through select_suites safe_mode: {events_eq}"
    sel_eq = sel_eq_events[-1]["result"]
    assert sel_eq["source"] == "safe_mode" and sel_eq["safe_mode"] is True, (
        f"pin_sha == head_sha must enter safe_mode, got {sel_eq!r}"
    )
    assert sel_eq["safe_mode_reason"] == "engine-failure", sel_eq
    assert any(f.get("kind") == "safe_mode" for f in sel_eq.get("findings") or ()), sel_eq
    assert set(sel_eq["use"]) == expected_universe and emitted_eq == expected_universe, (
        f"safe_mode must select every suite in the universe ({sorted(expected_universe)}), "
        f"got select_suites={sorted(sel_eq['use'])}, matrix={sorted(emitted_eq)}"
    )
    assert "safe_mode" in (summary_eq + "\n" + proc_eq.stdout), (
        "safe_mode activation must be recorded in GITHUB_STEP_SUMMARY or stdout"
    )


def test_production_entrypoints_wire_build_cutover_coordinator_and_pinned_runner():
    cutover_callers: list[str] = []
    coordinator_callers: list[str] = []
    pinned_runner_callers: list[str] = []
    pin_file_readers: list[str] = []

    for path in _production_python_files():
        _, called, literals = _module_imports_and_calls(path)
        rel = path.relative_to(ROOT).as_posix()
        if _matches_target(called, "build_cutover", "select_suites"):
            cutover_callers.append(rel)
        if _matches_target(called, "build_coordinator_reader", "read_coordinator_state"):
            coordinator_callers.append(rel)
        if _matches_target(called, "build_pinned_runner", "read_engine_pin") and _matches_target(
            called, "build_pinned_runner", "validate_engine_pin"
        ):
            pinned_runner_callers.append(rel)
            if any("engine-pin.yaml" in lit for lit in literals):
                pin_file_readers.append(rel)

    assert cutover_callers, (
        "no production entrypoint imports and calls loop.build_cutover.select_suites"
    )
    assert coordinator_callers, (
        "no production entrypoint imports and calls loop.build_coordinator_reader.read_coordinator_state"
    )
    assert pinned_runner_callers, (
        "no production entrypoint imports and calls both loop.build_pinned_runner.read_engine_pin "
        "and loop.build_pinned_runner.validate_engine_pin"
    )
    assert pin_file_readers, (
        "production entrypoint wiring loop.build_pinned_runner must read build/engine-pin.yaml"
    )
