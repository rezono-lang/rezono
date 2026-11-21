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
from pathlib import Path
import re

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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/build-reconciliation.md: .github/workflows/ci.yml must execute "
           "build/ on the pinned earlier main engine commit read from build/engine-pin.yaml "
           "and derive CI test selection from verified build/ pack publications via "
           "loop/build_cutover.py and loop/build_pinned_runner.py rather than calling "
           "components.py ci-matrix.",
)
def test_ci_workflow_executes_build_pack_on_pinned_engine_without_components_ci_matrix():
    from loop.build_pinned_runner import read_engine_pin

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

    # 2. The discover workflow and its invoked production scripts must read build/engine-pin.yaml,
    #    validate the pinned earlier main commit, evaluate build/, and select suites through build_cutover.
    invoked_scripts = _discover_invoked_python_files(exec_lines)
    all_called: set[str] = set()
    all_strings: set[str] = set(exec_lines)
    for script in invoked_scripts:
        _, called, literals = _module_imports_and_calls(script)
        all_called.update(called)
        all_strings.update(literals)

    reads_pin_file = any("engine-pin.yaml" in text for text in all_strings)
    assert reads_pin_file, (
        ".github/workflows/ci.yml discover path does not read build/engine-pin.yaml"
    )
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

    invokes_pack_pipeline = any(
        any(tok in target for tok in ("rezono_compiler", "rezono_publisher", "rezono_checker"))
        for target in all_called
    ) or any(
        any(tok in text for tok in ("rezono_compiler", "rezono_publisher", "rezono_checker", "build/pack.yaml"))
        for text in all_strings
    )
    assert invokes_pack_pipeline, (
        ".github/workflows/ci.yml discover path must compile, publish, and check the build/ pack "
        "on the pinned engine"
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
