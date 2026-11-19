#!/usr/bin/env python3
"""Discover repository components from directory structure without a central list."""

from __future__ import annotations

import argparse
from collections import Counter
from fnmatch import fnmatchcase
import posixpath
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".basedpyright",
    ".git",
    ".github",
    ".hypothesis",
    ".pytest_cache",
    ".venv",
    "LICENSES",
    "__pycache__",
    "blocked",
    "build",
    "compiled",
    "dist",
    "docs",
    "generated",
    "node_modules",
    "requirements",
    "scripts",
    "target",
    "to-port",
}


@dataclass(frozen=True)
class Component:
    folder: str
    kind: str  # "contracts" | "python" | "node"


def _has_py_tests(directory: Path) -> bool:
    if any(directory.glob("test_*.py")) or any(directory.glob("*_test.py")):
        return True
    tests_dir = directory / "tests"
    return tests_dir.is_dir() and (
        any(tests_dir.glob("test_*.py")) or any(tests_dir.glob("*_test.py"))
    )


def _has_node_test_script(pkg_json: Path, *, keep_invalid: bool = False) -> bool:
    if keep_invalid and pkg_json.is_symlink():
        return True
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return keep_invalid
    except UnicodeDecodeError:
        if keep_invalid:
            return True
        raise
    if keep_invalid and not isinstance(data, dict):
        return True
    scripts = data.get("scripts")
    return isinstance(scripts, dict) and bool(scripts.get("test"))


def discover_components(root: Path = ROOT, *, keep_invalid_node: bool = False) -> list[Component]:
    found: list[Component] = []

    def walk(current: Path, depth: int) -> None:
        if depth > 3:
            return
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if keep_invalid_node and child.is_symlink():
                continue
            rel = child.relative_to(root).as_posix()
            pkg_json = child / "package.json"
            if ((keep_invalid_node and pkg_json.is_symlink()) or pkg_json.is_file()) and _has_node_test_script(
                pkg_json, keep_invalid=keep_invalid_node
            ):
                found.append(Component(folder=rel, kind="node"))
                continue
            if (child / "check.sh").is_file() and (child / "gen-types.sh").is_file():
                found.append(Component(folder=rel, kind="contracts"))
                continue
            if (child / "pyproject.toml").is_file() or _has_py_tests(child):
                found.append(Component(folder=rel, kind="python"))
                continue
            walk(child, depth + 1)

    walk(root, 1)
    return sorted(found, key=lambda c: c.folder)


def discover_python_packages(root: Path = ROOT) -> list[str]:
    packages: list[str] = []

    def walk(current: Path, depth: int) -> None:
        if depth > 3:
            return
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if (child / "pyproject.toml").is_file():
                packages.append(child.relative_to(root).as_posix())
                continue
            walk(child, depth + 1)

    walk(root, 1)
    return sorted(packages)


def _git_changed_files(root: Path, base_ref: str | None, before_sha: str | None) -> list[str] | None:
    """Return changed file paths relative to root, or None when everything must run."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "workflow_dispatch":
        return None
    if event == "merge_group":
        base = os.environ.get("MERGE_GROUP_BASE_SHA", "")
        head = os.environ.get("MERGE_GROUP_HEAD_SHA", "")
        if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
            return None
        def git(*arguments: str):
            return subprocess.run(["git", *arguments], cwd=root, capture_output=True)
        if git("rev-parse", "HEAD").stdout.decode().strip() != head:
            return None
        if git("merge-base", "--is-ancestor", base, head).returncode:
            return None
        revisions = [base, head]
    elif base_ref:
        # Discovery checks out full history, including the PR's target branch.
        revisions = [f"origin/{base_ref}...HEAD"]
    elif before_sha and re.fullmatch(r"(?!0{40})[0-9a-f]{40}", before_sha):
        revisions = [before_sha, "HEAD"]
    else:
        return None
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", *revisions, "--"],
        cwd=root, capture_output=True,
    )
    if result.returncode:
        return None
    return [os.fsdecode(name) for name in result.stdout.split(bytes(1)) if name]


# Components consumed by other checks via files or subprocesses,
# including the offline runner's replay of a loop and the loop's admission proof.
# A change to a shared library, fixture tree or unknown component runs everything.
FILE_CONSUMERS = {
    "k8s-admission": ("loop",),
    "loop": ("run",),
    "run": (),
    "deploy/profiles/edge": ("edge/publisher",),
}


def outside_cluster_plugin(path: Path, manifest: Path) -> bool:
    """The loop's pytest distribution ships only its explicitly listed modules."""
    relative = path.relative_to("loop")
    try:
        packaging = tomllib.loads(manifest.read_text(encoding="utf-8"))["tool"]["setuptools"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not isinstance(packaging, dict) or set(packaging) != {"py-modules"}:
        return False
    modules = packaging["py-modules"]
    if not isinstance(modules, list) or not modules or not all(isinstance(m, str) and m.isidentifier() for m in modules):
        return False
    if relative.parent == Path("."):
        return (relative.suffix == ".py" and relative.name not in {"setup.py", "conftest.py"}
                and relative.stem not in modules)
    return relative.parent == Path("tests") and relative.match("test_*.py")


def affected_components(
    components: list[Component], changed_files: list[str] | None
) -> list[Component]:
    if changed_files is None:
        return list(components)
    by_folder = {c.folder: c for c in components}
    selected: set[str] = set()
    pending: list[str] = []
    for path in changed_files:
        owner = next((c for c in components if path.startswith(c.folder + "/")), None)
        if owner is None:
            # Markdown, golden files and shared packs are read by component tests.
            return list(components)
        selected.add(owner.folder)
        source = Path(path)
        manifest = ROOT / owner.folder / "pyproject.toml"
        if (owner.kind == "contracts" or source.name in {"pyproject.toml", "package.json", "conftest.py"}
                or (manifest.exists() and not (owner.folder == "loop" and outside_cluster_plugin(source, manifest)))):
            return list(components)
        # Tests can themselves be imported as cross-component oracles. Shared
        # source and test roots have no isolation contract, so keep full coverage.
        # The leaf components below use the same file-consumer closure for test
        # entry points and for production inputs.
        pending.append(owner.folder)
    visited: set[str] = set()
    while pending:
        folder = pending.pop()
        if folder in visited:
            continue
        visited.add(folder)
        if folder not in FILE_CONSUMERS:
            return list(components)
        for consumer in FILE_CONSUMERS[folder]:
            if consumer not in by_folder:
                return list(components)
            selected.add(consumer)
            pending.append(consumer)
    return [c for c in components if c.folder in selected]


# These reads are outside package metadata. Test imports, subprocess readers and
# build inputs count just as a declared library dependency does.
PR_FILE_CONSUMERS = {
    "admission": ("examples",),
    "canon": ("edge/plugins/connectors", "examples", "k8s-admission", "loop"),
    "checker": ("compiler", "examples", "k8s-admission", "loop", "run", "tests/slip"),
    "compiler": ("admission", "checker", "edge/plugins/connectors", "examples", "loop", "publication", "run",
                 "tests/slip"),
    "edge/plugins/connectors": ("examples",),
    "contracts": ("admission", "canon", "checker", "compiler", "edge/plugins/connectors", "loop", "publication", "rezono",
                  "tests/slip"),
    "edge/gate": ("tests/slip", "tools/repl", "tools/mcp"),
    "edge/publisher": ("compiler", "deploy/profiles/edge", "edge/plugins/connectors", "examples", "k8s-admission", "run",
                       "tests/slip"),
    "loop": ("examples",),
    "publication": ("checker", "compiler", "edge/plugins/connectors", "edge/publisher", "examples", "tests/slip"),
    "rezono": ("compiler", "tests/slip"),
    "tools/repl": ("tests/slip", "tools/mcp"),
    # examples/test_slip_claims.py draws the slip with the helpers of tests/slip (decisions/viewer-slip.md).
    "tests/slip": ("examples",),
}
# These are test entry points and a private subprocess helper, rather than inputs to
# the installed packages. Their shared corpus is still routed by SHARED_READERS.
PR_TEST_LEAVES = frozenset({
    "checker/tests/test_neutral_conformance_checker.py",
    "compiler/tests/test_neutral_conformance_compiler.py",
    "compiler/tests/rezono/neutral-answer-cases.mjs",
    "compiler/tests/rezono/test_neutral_answer_cases.py",
})
LANGUAGE_COVERAGE_LEAVES = (
    "compiler/tests/rezono/language_usage.py",
    "compiler/tests/rezono/test_language_usage.py",
)
LANGUAGE_COVERAGE_REPORT = "docs/rezono/language-coverage.md"
LANGUAGE_COVERAGE_COMMAND = (
    "Run `python compiler/tests/rezono/language_usage.py` from the repository root for the current inventory."
)

# The generated command and the link targets in three documentation pages.
LANGUAGE_COVERAGE_MANUAL_REFERENCES = {
    LANGUAGE_COVERAGE_REPORT: LANGUAGE_COVERAGE_COMMAND,
    "docs/README.md": "(rezono/language-coverage.md)",
    "docs/compiler/rules.md": "(../rezono/language-coverage.md)",
    "docs/formal.md": "(rezono/language-coverage.md)",
}
PACK_READERS = ("admission", "checker", "compiler", "edge/plugins/connectors", "edge/publisher", "examples",
                "k8s-admission", "loop", "publication", "rezono", "run")
SHARED_READERS = {
    "examples/platform/proof_cases/role-publication-cases.ts": ("tools/repl", "tools/mcp"),
    "docs/compiler/pack.md": ("compiler",),
    "docs/publication/l0.md": ("edge/plugins/connectors",),
    "docs/publication/cases/": ("compiler", "edge/plugins/connectors", "publication"),
    "docs/rezono/cases/": ("compiler", "rezono"),
    "docs/semantics/value-cases.yaml": ("compiler", "rezono"),
    "docs/semantics/witness-alternatives-cases.yaml": ("checker", "compiler"),
    "docs/tutorial.md": ("examples",),
    "decisions/language-native-rules.md": ("compiler",),
    "decisions/publication-case-pins.md": ("compiler",),
    "decisions/conformance-*.md": ("compiler",),
    "tests/fixtures/neutral/": ("checker", "compiler", "edge/publisher", "rezono"),
    "tests/fixtures/slip/": ("examples", "tests/slip"),
    "tests/fixtures/turns/": ("checker", "edge/publisher"),
    # The verb bar of the slip (decisions/viewer-slip.md): its contract test and the page tests read it.
    "packs/std-view/": ("contracts", "tests/slip"),
    "viewer/slip/": ("compiler", "examples", "tests/slip"),
    "viewer/messages/": ("compiler", "examples", "tests/slip"),
    "tests/conformance/": ("checker", "compiler", "edge/publisher", "rezono"),
    "packs/": PACK_READERS,
    "examples/": PACK_READERS,
    "examples/**/expected/**": ("contracts",),
    "edge/plugins/*/plugin.yaml": ("contracts",),
    "contracts/output-index.yaml": ("edge/publisher",),
    "viewer/src/lib/canon.ts": ("compiler", "edge/publisher", "rezono"),
}

PYTHON_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?"
SPECIFIER = r"(?:===|==|!=|<=|>=|~=|<|>)\s*[^\s,;()]+"
SPECIFIERS = rf"{SPECIFIER}(?:\s*,\s*{SPECIFIER})*"
REQUIREMENT = re.compile(
    rf"\s*({PYTHON_NAME})(?:\s*\[\s*{PYTHON_NAME}(?:\s*,\s*{PYTHON_NAME})*\s*\])?"
    rf"\s*(?:\(\s*{SPECIFIERS}\s*\)|{SPECIFIERS}|@\s*[^\s;]+)?\s*(?:;\s*\S.*)?"
)
NODE_GROUPS = ("dependencies", "optionalDependencies", "peerDependencies", "devDependencies")
MANIFEST_NAMES = {"pyproject.toml", "package.json"}


@dataclass(frozen=True)
class Package:
    path: str
    kind: str
    name: str
    owner: str | None
    dependencies: tuple[tuple[str, str], ...]
    workspaces: tuple[str, ...] = ()


def shared_readers(path: str) -> set[str] | None:
    """Known direct readers, or None when the file has no safe selection."""
    if path.startswith(("docs/", "decisions/")) and path.endswith(".md"):
        readers: set[str] | None = set()
    else:
        readers = None
    for pattern, owners in SHARED_READERS.items():
        matches = path.startswith(pattern) if pattern.endswith("/") else fnmatchcase(path, pattern)
        if matches:
            if readers is None:
                readers = set()
            readers.update(owners)
    return readers


def component_owner(path: str, folders: set[str]) -> str | None:
    while "/" in path:
        path = path.rsplit("/", 1)[0]
        if path in folders:
            return path
    return None


def git_output(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.PIPE)


def independent_test_leaves(root: Path, revision: str, leaves: dict[str, list[str]], folders: set[str],
                            *, manual_references: dict[str, str] | None = None) -> bool:
    """Refuse a narrowed test selection if either tree names an outside reader."""
    leaf_paths = {path for paths in leaves.values() for path in paths}
    tracked = sorted(leaf_paths | (manual_references or {}).keys())
    raw = git_output(root, "ls-tree", "-z", revision, "--", *tracked)
    entries = [entry for entry in raw.split(b"\0") if entry]
    if any(entry.split(b" ", 1)[0] not in {b"100644", b"100755"} for entry in entries):
        return False
    if manual_references is not None and len(entries) != len(tracked):
        return False
    for owner, paths in leaves.items():
        # Search the basename without its extension as well, so Python imports,
        # run_path calls and subprocess filenames all count as readers.
        # The selector and its matrix regression run as the discovery step.
        names = [Path(path).name if Path(path).suffix == ".md" else Path(path).stem for path in paths]
        for page, expected in (manual_references or {}).items():
            document = git_output(root, "show", f"{revision}:{page}").decode("utf-8")
            if "\0" in document:
                return False
            if page in leaf_paths:
                references = [line for line in document.splitlines() if any(name in line for name in names)]
                if references != [expected]:
                    return False
                continue
            link = re.search(r"\[[^\]\r\n]+\]" + re.escape(expected), document)
            if link is None or document.count(expected) != 1:
                return False
            if any(name in document.replace(expected, "", 1) for name in names):
                return False
        patterns = [arg for name in names for arg in ("-e", name)]
        result = subprocess.run(
            ["git", "grep", "-F", "-I", "-l", "-z", *patterns, revision, "--", ".",
             ":(exclude,top)scripts/components.py", ":(exclude,top).github/workflows/tests/test_components.py"],
            cwd=root, capture_output=True,
        )
        if result.returncode not in (0, 1):
            raise ValueError("cannot check readers of a test leaf")
        prefix = revision + ":"
        for item in result.stdout.split(b"\0"):
            if item:
                entry = os.fsdecode(item)
                if not entry.startswith(prefix):
                    return False
                name = entry[len(prefix):]
                if component_owner(name, folders) == owner:
                    continue
                if name not in (manual_references or {}):
                    return False
    return True


def language_coverage_only(root: Path, base: str, head: str, changed: list[str], folders: set[str]) -> bool | None:
    """Return None outside the coverage-only scope and verify both trees within it."""
    changes = set(changed)
    leaves = set(LANGUAGE_COVERAGE_LEAVES)
    if changes.isdisjoint(leaves) or not changes <= leaves | {LANGUAGE_COVERAGE_REPORT}:
        return None
    return "compiler" in folders and all(
        independent_test_leaves(root, revision, {"compiler": [*LANGUAGE_COVERAGE_LEAVES, LANGUAGE_COVERAGE_REPORT]}, folders,
                                manual_references=LANGUAGE_COVERAGE_MANUAL_REFERENCES)
        for revision in (base, head)
    )


def pull_request_range(root: Path, base_ref: str) -> tuple[str, str, list[str]]:
    if not base_ref:
        raise ValueError("no pull request base ref")
    head = git_output(root, "rev-parse", "HEAD").decode().strip()
    bases = git_output(root, "merge-base", "--all", f"origin/{base_ref}", head).decode().split()
    if len(bases) != 1 or not all(re.fullmatch(r"[0-9a-f]{40}", rev) for rev in [head, *bases]):
        raise ValueError("ambiguous pull request revision range")
    base = bases[0]
    contents = git_output(root, "diff", "--no-renames", "--name-only", "-z", base, head, "--")
    return base, head, [os.fsdecode(name) for name in contents.split(b"\0") if name]


def python_name(name: str) -> str:
    if not re.fullmatch(PYTHON_NAME, name):
        raise ValueError("invalid Python package name")
    return re.sub(r"[-_.]+", "-", name).lower()


def read_package(path: str, raw: bytes, folders: set[str]) -> Package:
    owner = component_owner(path, folders)
    if path.endswith("pyproject.toml"):
        data = tomllib.loads(raw.decode("utf-8"))
        project = data["project"]
        dynamic = project.get("dynamic", [])
        if (not isinstance(dynamic, list) or not all(isinstance(key, str) for key in dynamic)
                or {"name", "dependencies", "optional-dependencies"} & set(dynamic)
                or "dependency-groups" in data):
            raise ValueError("dynamic package dependencies")
        extras = project.get("optional-dependencies", {})
        groups = [project.get("dependencies", []), data.get("build-system", {}).get("requires", []), *extras.values()]
        dependencies = []
        for requirements in groups:
            if not isinstance(requirements, list):
                raise ValueError("expected a list of Python requirements")
            for requirement in requirements:
                match = REQUIREMENT.fullmatch(requirement)
                if match is None or re.search(r"@\s*file:", requirement, re.IGNORECASE):
                    raise ValueError("unresolved Python requirement")
                dependencies.append((python_name(match[1]), ""))
        return Package(path, "python", python_name(project["name"]), owner, tuple(dependencies))

    data = json.loads(raw)
    workspace = data.get("workspaces", [])
    if isinstance(workspace, dict):
        workspace = workspace["packages"]
    if not isinstance(workspace, list) or any(not isinstance(p, str) or not p for p in workspace):
        raise ValueError("expected workspace path patterns")
    name = data.get("name", "")
    if not isinstance(name, str) or (not name and not workspace):
        raise ValueError("package has no name")
    dependencies = []
    for group in NODE_GROUPS:
        for dependency, version in data.get(group, {}).items():
            if not dependency or not isinstance(version, str) or not version:
                raise ValueError("invalid Node dependency")
            dependencies.append((dependency, version))
    return Package(path, "node", name, owner, tuple(dependencies), tuple(workspace))


def node_target(package: Package, name: str, version: str,
                providers: dict[tuple[str, str], Package], paths: dict[str, Package]) -> Package | None:
    protocol, _, value = version.partition(":")
    if protocol in ("file", "link") or protocol == "workspace" and value.startswith("."):
        local = posixpath.normpath(posixpath.join(posixpath.dirname(package.path), value, "package.json"))
        return paths[local]  # an unresolved local package cannot be pruned safely
    if protocol in ("workspace", "npm"):
        alias = value.rsplit("@", 1)[0] if "@" in value[1:] else value
        if protocol == "npm" or (protocol == "workspace" and alias != value):
            name = alias
    target = providers.get(("node", name))
    if protocol == "workspace" and target is None:
        raise ValueError("workspace dependency does not name a local package")
    return target


def declared_dependents(root: Path, revision: str, folders: set[str],
                        cache: dict[str, bytes]) -> dict[str, set[str]]:
    manifests = {}
    for item in git_output(root, "ls-tree", "-r", "-z", revision).split(b"\0"):
        if not item:
            continue
        entry, path = item.split(b"\t", 1)
        name = os.fsdecode(path)
        basename = name.rsplit("/", 1)[-1]
        if basename == "pnpm-workspace.yaml":
            raise ValueError("workspace topology needs full selection")
        if basename not in MANIFEST_NAMES:
            continue
        mode, kind, oid = entry.decode("ascii").split()
        if mode not in ("100644", "100755") or kind != "blob":
            raise ValueError("manifest is not a regular file")
        if oid not in cache:
            cache[oid] = git_output(root, "cat-file", "blob", oid)
        manifests[name] = read_package(name, cache[oid], folders)

    providers = {}
    for package in manifests.values():
        key = (package.kind, package.name)
        if package.name:
            if key in providers:
                raise ValueError("ambiguous package name")
            providers[key] = package

    dependents: dict[str, set[str]] = {}
    for package in manifests.values():
        for name, version in package.dependencies:
            target = (node_target(package, name, version, providers, manifests) if package.kind == "node"
                      else providers.get(("python", name)))
            if target and package.owner:
                if not target.owner:
                    raise ValueError("local dependency has no component")
                dependents.setdefault(target.owner, set()).add(package.owner)
        if package.workspaces and package.owner:
            directory = posixpath.dirname(package.path)
            for pattern in package.workspaces:
                if pattern.startswith(("!", "/", "..")) or "{" in pattern or "\\" in pattern:
                    raise ValueError("unsupported workspace pattern")
                for target in manifests.values():
                    if (target.kind == "node" and target.owner and target is not package
                            and fnmatchcase(posixpath.dirname(target.path),
                                           posixpath.join(directory, pattern.removeprefix("./").rstrip("/")))):
                        dependents.setdefault(target.owner, set()).add(package.owner)
    return dependents


def pull_request_components(components: list[Component], root: Path, base_ref: str) -> list[Component]:
    """Select consumers of changes against the exact PR range, without executing manifests."""
    folders = {c.folder for c in components}
    direct, pending = set(), set()
    leaves: dict[str, list[str]] = {}
    try:
        base, head, changed = pull_request_range(root, base_ref)
        coverage = language_coverage_only(root, base, head, changed, folders)
        if coverage is False:
            return list(components)
        if coverage:
            return [component for component in components if component.folder == "compiler"]
        for path in changed:
            owner = component_owner(path, folders)
            readers = shared_readers(path)
            if readers is not None:
                direct.update(readers & folders)
                if path == "viewer/src/lib/canon.ts":
                    pending.update(readers & folders)
            if owner:
                source = Path(path)
                # The converter regression parses every tracked non-fixture Datalog file.
                if source.suffix == ".dl" and "fixtures" not in source.parts:
                    direct.add("compiler")
                if owner == "loop" and not outside_cluster_plugin(source, root / "loop/pyproject.toml"):
                    return list(components)  # the shipped plugin runs in every pytest process
                if path in PR_TEST_LEAVES:
                    direct.add(owner)
                    leaves.setdefault(owner, []).append(path)
                else:
                    pending.add(owner)
            elif readers is None or path.startswith("edge/plugins/"):
                return list(components)
        if not pending and not leaves:
            return [c for c in components if c.folder in direct]
        if leaves and not all(independent_test_leaves(root, revision, leaves, folders) for revision in (base, head)):
            return list(components)
        cache: dict[str, bytes] = {}
        edges: dict[str, set[str]] = {}
        for graph in (FILE_CONSUMERS, PR_FILE_CONSUMERS,
                      declared_dependents(root, base, folders, cache), declared_dependents(root, head, folders, cache)):
            for source, consumers in graph.items():
                edges.setdefault(source, set()).update(set(consumers) & folders)
    except (OSError, ValueError, AttributeError, KeyError, TypeError, subprocess.CalledProcessError):
        return list(components)
    affected = set()
    while pending:
        folder = pending.pop()
        if folder not in affected:
            affected.add(folder)
            pending.update(edges.get(folder, ()))
    return [c for c in components if c.folder in direct | affected]


# Files are assigned to jobs round-robin. Within a job pytest items share the
# runner's cores, so one large parametrized file can use more than one core.
FORMS_MODULE = "examples/subsidy/test_subsidy_forms.py"
INDEPENDENT_PUBLICATIONS = "examples/subsidy/test_subsidy.py"
RULE_EXAMPLES = "examples/test_rules.py"
SHARDS = {"compiler": 3, "edge/publisher": 2}
PARALLEL = {"compiler", "examples", "edge/publisher"}


def test_files(folder: str) -> list[str]:
    directory = ROOT / folder
    return sorted({
        path.relative_to(ROOT).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in directory.rglob(pattern)
        if path.is_file() and "node_modules" not in path.relative_to(directory).parts
    })


def shard_count(folder: str) -> int:
    files = test_files(folder)
    if folder != "examples":
        return min(SHARDS.get(folder, 1), max(1, len(files)))
    # Run 44301601328 placed the two CPU-heavy modules on the same runner.
    # Choose the fewest round-robin partitions that separate the three long
    # example modules, even as new test files change their sorted positions.
    heavy = {RULE_EXAMPLES, INDEPENDENT_PUBLICATIONS, FORMS_MODULE}
    positions = [i for i, file in enumerate(files) if file in heavy]
    candidates = range(max(1, len(positions)), min(8, max(1, len(files))) + 1)
    return min(candidates, key=lambda n: (len(positions) - len({i % n for i in positions}), n))


def runner_cores() -> int:
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    return min(4, available or 1)


def check_contracts() -> int:
    # The checker discovers fixtures relative to its own location. Each copy
    # runs the original checker with all schemas and a disjoint fixture set.
    source = ROOT / "contracts"
    fixtures = sorted((source / "fixtures").glob("*/*/*/*.yaml"))
    workers = runner_cores()

    def check(worker: int) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "contracts"
            excluded = set(fixtures) - set(fixtures[worker::workers])

            def ignore(directory: str, names: list[str]) -> list[str]:
                return [name for name in names if Path(directory) / name in excluded]

            shutil.copytree(source, copy, ignore=ignore)
            return subprocess.run(
                ["bash", str(copy / "check.sh")], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, check=False,
            )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        status = 0
        for result in pool.map(check, range(workers)):
            print(result.stdout, end="", flush=True)
            status = status or result.returncode
        return status


def inventory_path(directory: Path, folder: str) -> Path:
    return directory / folder / "items.json"


def collect_component(folder: str, directory: Path) -> int:
    import pytest

    sys.path.insert(0, str(ROOT))
    dest = inventory_path(directory, folder)
    dest.parent.mkdir(parents=True, exist_ok=True)
    collection_report = dest.with_name("collection.xml")
    items: list[str] = []
    cluster: list[str] = []
    deselected: list[str] = []
    config_path = None

    class Inventory:
        def pytest_deselected(self, items):
            deselected.extend(item.nodeid for item in items)

        def pytest_collection_finish(self, session):
            nonlocal config_path
            items.extend(item.nodeid for item in session.items)
            cluster.extend(item.nodeid for item in session.items if item.get_closest_marker("cluster"))
            config_path = str(session.config.inipath.relative_to(ROOT)) if session.config.inipath else None

    result = pytest.main(
        [folder, "--collect-only", "--rezono-cluster", "-qq", "--rootdir", str(ROOT),
         f"--junitxml={collection_report}"],
        plugins=[Inventory()],
    )
    if deselected:
        print(f"{folder}: tests deselected during full inventory: {deselected}", file=sys.stderr)
        return 1
    if result == pytest.ExitCode.NO_TESTS_COLLECTED:
        # A component without tests is valid only with the original blocked-file evidence.
        if folder == "contracts/python" or subprocess.call(
            [sys.executable, str(ROOT / "scripts/red_list.py"), "--all-tests-blocked", folder]
        ):
            return 1
    elif result:
        return int(result)
    if len(items) != len(set(items)):
        raise ValueError(f"{folder}: duplicate pytest node IDs in the inventory")
    files = sorted(set(test_files(folder)) | {i.split("::", 1)[0] for i in items})
    dest.write_text(json.dumps({"items": items, "cluster": cluster, "files": files, "config": config_path}),
                    encoding="utf-8")
    print(f"{folder}: inventoried {len(items)} node IDs from {len(files)} test files", flush=True)
    return 0


def pytest_folder(component: dict) -> str:
    return component["folder"] + ("/python" if component["kind"] == "contracts" else "")


def collect_matrix(matrix: list[dict], directory: Path) -> int:
    folders = sorted({pytest_folder(c) for c in matrix})
    def collect(folder: str) -> int:
        return subprocess.call([sys.executable, __file__, "collect-component", folder, str(directory)])
    with ThreadPoolExecutor(max_workers=runner_cores()) as pool:
        statuses = list(pool.map(collect, folders))
        return next((code for code in statuses if code), 0)


def shard_items(plan: dict, shard: int, total: int) -> list[str]:
    files = set(plan["files"][shard::total])
    return [node for node in plan["items"] if node.split("::", 1)[0] in files]


def weighted_workers(items: list[str], workers: int, weights: dict[str, int], default: int) -> list[list[str]]:
    """Assign expensive IDs first, resolving ties in inventory order, then retain pytest's order."""
    loads = [0] * workers
    assigned = {}
    for node in sorted(items, key=lambda item: -weights.get(item, default)):
        slot = min(range(workers), key=loads.__getitem__)
        assigned[node] = slot
        loads[slot] += weights.get(node, default)
    groups = [[] for _ in range(workers)]
    for node in items:
        groups[assigned[node]].append(node)
    return groups


def worker_items(folder: str, items: list[str], workers: int) -> list[list[str]]:
    if folder == "compiler" and workers > 1:
        # Each timing is one of its worker's five reported durations in the
        # linked run (or the per-ID additional source). The default uses the
        # original run: unreported worker time divided by the remaining IDs.
        profile = json.loads((ROOT / ".github/workflows/compiler-duration-profile.json").read_text(encoding="utf-8"))
        return weighted_workers(items, workers, profile["call_ms"], profile["default_ms"])
    if folder != "examples" or workers == 1:
        return [items[n::workers] for n in range(workers)]
    # Keep the examples' file-scoped accumulation and the two independent immutable readers.
    forms = FORMS_MODULE
    readers = sorted(i for i in items if i.split("::", 1)[0] == forms)
    groups = [[] for _ in range(workers)]
    offset = 2 if readers and workers > 2 else 0
    if offset:
        # Keep pytest collection order within each execution process.
        # The second publication and the independent standards readers dominate
        # this module. Give the table checks to the shorter reader as well.
        costs = {
            forms + "::test_a_ledger_payment_does_not_change_the_policy_adviser_s_form": 79_000,
            forms + "::test_each_role_s_standards_exports_pass_their_readers": 55_000,
            forms + "::test_each_role_s_tables_give_its_dataset_hash_alone": 7_700,
        }
        first = set(weighted_workers(readers, 2, costs, 200)[0])
        for node in items:
            if node in first:
                groups[0].append(node)
            elif node in readers:
                groups[1].append(node)
    others = [i for i in items if not offset or i.split("::", 1)[0] != forms]
    # The independent subsidy tests each publish into their own tmp_path.
    # Keep cached pack states and all other module-scoped fixtures together.
    def unit(node: str) -> str:
        path = node.partition("::")[0]
        return node if path == INDEPENDENT_PUBLICATIONS else path

    by_unit = Counter(map(unit, others))
    # Rounded worker durations from run 44300384730. Unknown files cost one
    # second per collected item, and new independent publications cost 17s.
    weights = {
        key: (17 if key.startswith(INDEPENDENT_PUBLICATIONS + "::") else count)
        for key, count in by_unit.items()
    }
    weights.update({RULE_EXAMPLES: 125, "examples/test_examples.py": 75,
                    "examples/subsidy/test_proposal_path.py": 45,
                    "examples/subsidy/test_assessment_transition.py": 30,
                    "examples/subsidy/test_tutorial.py": 30})
    for index, units in enumerate(weighted_workers(sorted(by_unit), workers - offset, weights, 1), offset):
        assigned = set(units)
        groups[index].extend(node for node in others if unit(node) in assigned)
    return groups


def execute_worker(assignment: Path, journal: Path, report: Path) -> int:
    import pytest

    sys.path.insert(0, str(ROOT))
    data = json.loads(assignment.read_text(encoding="utf-8"))
    expected = data["items"]
    with journal.open("w", encoding="utf-8", buffering=1) as evidence:
        if not expected:
            return 0

        class Evidence:
            def pytest_collection_finish(self, session):
                found = [i.nodeid for i in session.items]
                if Counter(found) != Counter(expected):
                    raise pytest.UsageError("The requested pytest IDs resolved to a different set")

            def pytest_runtest_logstart(self, nodeid, location):
                print(json.dumps(["start", nodeid]), file=evidence)

            @pytest.hookimpl(wrapper=True, tryfirst=True)
            def pytest_runtest_makereport(self, item, call):
                from rezono_cluster import CLUSTER_SKIP_REASON

                result = yield
                if (item.get_closest_marker("cluster") and call.when == "setup" and result.skipped
                        and call.excinfo and isinstance(call.excinfo.value, pytest.skip.Exception)
                        and str(call.excinfo.value) == CLUSTER_SKIP_REASON):
                    print(json.dumps(["cluster-skip", item.nodeid]), file=evidence)
                    print(f"{item.nodeid}: {CLUSTER_SKIP_REASON}")
                return result

            def pytest_runtest_logfinish(self, nodeid, location):
                print(json.dumps(["finish", nodeid]), file=evidence)

        args = ["-q", "--rezono-report-cluster", "--durations=5", "--rootdir", str(ROOT), f"--junitxml={report}"]
        if data["config"]:
            args.extend(["-c", data["config"]])
        # Pytest resolves only assigned IDs, without walking the component again.
        plugins = [Evidence()]
        if "publication" in data:
            # These short-lived RDF graphs caused 63 full-heap collections
            # (20.6 s) in run 44302050936. Collect larger batches in these
            # dedicated processes; all generations and finalizers remain active.
            import gc
            young, middle, old = gc.get_threshold()
            gc.set_threshold(young * 8, middle, old)
            print(f"Publication worker GC thresholds: {gc.get_threshold()}", flush=True)
            sys.path.insert(0, str(ROOT / ".github/workflows"))
            from publication_fixture import PublicationProducer, PublicationReader

            share = data["publication"]
            plugin = PublicationProducer if share["producer"] else PublicationReader
            plugins.append(plugin(Path(share["directory"]), ROOT / FORMS_MODULE))
        return int(pytest.main([*args, "--", *expected], plugins=plugins))


def run_shard(folder: str, shard: int, total: int, plans: Path, reports: Path, receipts: Path) -> int:
    plan = json.loads(inventory_path(plans, folder).read_text(encoding="utf-8"))
    reports.mkdir(parents=True, exist_ok=True)
    evidence = receipts / folder
    evidence.mkdir(parents=True, exist_ok=True)
    selected = shard_items(plan, shard, total)
    groups = worker_items(folder, selected, runner_cores() if folder in PARALLEL else 1)
    if Counter(i for group in groups for i in group) != Counter(selected):
        raise ValueError("Worker assignments differ from the shard inventory")
    print(f"{folder} shard {shard+1}/{total}: {len(selected)} test IDs", flush=True)
    paired_readers = (folder == "examples" and len(groups) > 2 and
                      all(group and all(node.partition("::")[0] == FORMS_MODULE for node in group)
                          for group in groups[:2]))

    def execute(pair):
        index, nodes = pair
        assignment = reports / f"assignment-{index}.json"
        data = {"items": nodes, "config": plan["config"]}
        share = paired_readers and index < 2
        if share:
            data["publication"] = {"directory": directory, "producer": index == 0}
        try:
            assignment.write_text(json.dumps(data), encoding="utf-8")
            return subprocess.call([
                sys.executable, __file__, "execute-worker", str(assignment),
                str(evidence / f"{shard}-{index}.jsonl"), str(reports / f"pytest-{index}.xml"),
            ])
        finally:
            if share and index == 0:
                (Path(directory) / "producer-finished").touch()
    with tempfile.TemporaryDirectory(prefix="pytest-fixture-") as directory:
        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            statuses = list(pool.map(execute, enumerate(groups)))
        status = next((code for code in statuses if code), 0)
        if paired_readers and not status:
            for role in ("producer", "reader"):
                timing = (Path(directory) / f"{role}.json").read_text(encoding="utf-8")
                print(f"Current publication fixture {role}: {timing}", flush=True)
    # Write the expected number of journals even on failure, for diagnosis.
    (evidence / f"{shard}.json").write_text(json.dumps(len(groups)), encoding="utf-8")
    return status


def verify_execution(matrix: list[dict], plans: Path, receipts: Path) -> int:
    success = True
    for folder in sorted({pytest_folder(c) for c in matrix}):
        rows = [c for c in matrix if pytest_folder(c) == folder]
        plan = json.loads(inventory_path(plans, folder).read_text(encoding="utf-8"))
        all_items = Counter(plan["items"])
        cluster = Counter(plan["cluster"])
        expected_events = {"start": all_items, "finish": all_items, "cluster-skip": cluster}
        observed = {event: Counter() for event in expected_events}
        for row in rows:
            shard, total = row["shard"], row["total"]
            directory = receipts / folder
            expected = Counter(shard_items(plan, shard, total))
            shard_counts = {event: Counter() for event in expected_events}
            try:
                workers = json.loads((directory / f"{shard}.json").read_text(encoding="utf-8"))
                for index in range(workers):
                    journal = (directory / f"{shard}-{index}.jsonl").read_text(encoding="utf-8")
                    for line in journal.splitlines():
                        event, node = json.loads(line)
                        shard_counts[event][node] += 1
            except (OSError, ValueError, KeyError) as error:
                print(f"{folder} shard {shard+1}: incomplete evidence: {error}", file=sys.stderr)
                success = False
            for event, counts in shard_counts.items():
                observed[event].update(counts)
                required = expected & expected_events[event]
                if counts != required:
                    print(f"{folder} shard {shard+1} {event}: missing {list((required-counts).elements())}, "
                          f"extra {list((counts-required).elements())}", file=sys.stderr)
                    success = False
        for event, counts in observed.items():
            if counts != expected_events[event]:
                print(f"{folder}: {event} differs from full component inventory", file=sys.stderr)
                success = False
        print(f"{folder}: inventoried {len(plan['items'])}, started {observed['start'].total()}, "
              f"finished {observed['finish'].total()}, disposable cluster required {observed['cluster-skip'].total()}")
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List discovered component folders and kinds.")
    sub.add_parser("python-packages", help="Print editable Python package directories.")
    sub.add_parser("check-contracts", help="Validate all contract fixtures across runner cores.")
    shard_p = sub.add_parser("run-shard", help="Run the selected pytest file partition.")
    shard_p.add_argument("folder")
    shard_p.add_argument("shard", type=int)
    shard_p.add_argument("total", type=int)
    shard_p.add_argument("plans", type=Path)
    shard_p.add_argument("reports", type=Path)
    shard_p.add_argument("receipts", type=Path)
    collect = sub.add_parser("collect-component")
    collect.add_argument("folder")
    collect.add_argument("plans", type=Path)
    for name in ("inventory", "verify-execution"):
        command = sub.add_parser(name)
        command.add_argument("plans", type=Path)
        if name == "verify-execution":
            command.add_argument("receipts", type=Path)
    worker = sub.add_parser("execute-worker")
    for name in ("assignment", "journal", "report"):
        worker.add_argument(name, type=Path)
    matrix_p = sub.add_parser("ci-matrix", help="Emit GitHub Actions matrix outputs.")
    matrix_p.add_argument("--base-ref", default=os.environ.get("GITHUB_BASE_REF", ""))
    matrix_p.add_argument("--before", default=os.environ.get("GITHUB_EVENT_BEFORE", ""))

    args = parser.parse_args()
    if args.cmd == "check-contracts":
        return check_contracts()
    if args.cmd == "run-shard":
        return run_shard(args.folder, args.shard, args.total, args.plans, args.reports, args.receipts)
    if args.cmd == "inventory":
        return collect_matrix(json.loads(os.environ["PYTHON_MATRIX"]), args.plans)
    if args.cmd == "collect-component":
        return collect_component(args.folder, args.plans)
    if args.cmd == "execute-worker":
        return execute_worker(args.assignment, args.journal, args.report)
    if args.cmd == "verify-execution":
        return verify_execution(json.loads(os.environ["PYTHON_MATRIX"]), args.plans, args.receipts)
    if args.cmd == "list":
        for comp in discover_components():
            print(f"{comp.folder}\t{comp.kind}")
        return 0
    if args.cmd == "python-packages":
        print(" ".join(discover_python_packages()))
        return 0
    if args.cmd == "ci-matrix":
        pull_request = os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        comps = discover_components(keep_invalid_node=pull_request)
        if pull_request:
            active = pull_request_components(comps, ROOT, args.base_ref)
        else:
            changed = _git_changed_files(ROOT, args.base_ref or None, args.before or None)
            active = affected_components(comps, changed)
        py_items = [
            {"folder": c.folder, "kind": c.kind, "shard": shard, "total": total,
             "label": c.folder if total == 1 else f"{c.folder} {shard + 1}/{total}"}
            for c in active
            if c.kind in ("contracts", "python")
            for total in [shard_count(c.folder)]
            for shard in range(total)
        ]
        # A node component's pytest files run once, in its node job, which already
        # installs the component's packages; the exact-once inventory includes them.
        node_items = [
            {"folder": c.folder, "kind": c.kind, "pytest": bool(test_files(c.folder))}
            for c in active
            if c.kind == "node"
        ]
        pytest_items = py_items + [
            {"folder": item["folder"], "kind": "node", "shard": 0, "total": 1, "label": item["folder"]}
            for item in node_items
            if item["pytest"]
        ]
        editable_flags = " ".join(f"-e {pkg}" for pkg in discover_python_packages())
        lines = [
            f"python={json.dumps(py_items, separators=(',', ':'))}",
            f"has_python={'true' if py_items else 'false'}",
            f"node={json.dumps(node_items, separators=(',', ':'))}",
            f"has_node={'true' if node_items else 'false'}",
            f"pytest={json.dumps(pytest_items, separators=(',', ':'))}",
            f"has_pytest={'true' if pytest_items else 'false'}",
            f"python_editable={editable_flags}",
        ]
        out_path = os.environ.get("GITHUB_OUTPUT")
        if out_path:
            with open(out_path, "a", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
        for line in lines:
            print(line)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
