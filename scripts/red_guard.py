"""Read two Git trees as data and review changes to test evidence.

Without the planner label, only existing pytest xfail marks may be lifted or explained.
With it, protected paths may change, but a lifted mark must stand alone and every added
or changed mark must be strict. Either way, the reason of every added or changed mark is
literal text that starts with a milestone, and a changed reason keeps a milestone. Without
the label, a changed reason may move its mark to an earlier milestone but not to a later one.
Removed and changed evidence is reported either way.

One exception lets a planner complete evidence: with the label, a pull request may lift one
red mark beside new evidence data that test reads (added files under expected/, snapshots/
or vectors/), if it changes nothing else. red_before.py
then shows that the test is red on the base and green with the new evidence. A second one
lets a planner re-pin the imports of a fixture pack beside a lifted mark, to the hash the
guard computes for the imported pack at the head (decisions/fixture-pin-update.md).

A pull request that changes the checker or read access in a file that is not a test is
read before it lands: it needs the label `p1-read-` plus the full id of its head commit
(40 hex characters), whatever other labels it carries. A new push therefore needs a new label.
In the merge queue no labels are read and this rule does not apply.
"""
import argparse
import ast
from collections import Counter, namedtuple
import configparser
import copy
from fnmatch import fnmatchcase
import hashlib
import io
import json
from pathlib import PurePosixPath
import posixpath
import re
import subprocess
import sys
import tokenize
import tomllib


# The merge queue runs a candidate's own workflow files, so the workflows that define the
# required checks (`check` and `Light checks` in ci.yml, and the reusable cluster workflow
# that `check` aggregates) are policy as much as the guard that reviews them.
# So is what those workflows run from the candidate to decide which suites run and whether
# the cluster tests ran. These paths stay source as well: a pull request that changes them
# and adds a test still shows in red_before.py that the test fails on the base copy.
SOURCE_POLICY = {
    ".github/workflows/python-environment/action.yml", "loop/rezono_cluster.py",
    "scripts/cluster_worker_tasks.py", "scripts/role_publication_ci.py", "scripts/components.py",
    # The cluster task split imports fast_check.py, and the cluster workflow runs it for a
    # task; for a suite, select_tests.py chooses the cluster tests and nothing counts them.
    # ci.yml runs red_list.py to decide whether the milestones and skips hold.
    "scripts/fast_check.py", "loop/cluster/select_tests.py", "scripts/red_list.py",
}
POLICY = SOURCE_POLICY | {
    ".github/workflows/red-policy.yml",
    ".github/workflows/ci.yml", ".github/workflows/disposable-cluster.yml",
    ".github/workflows/resume-feldera-review.yml", "scripts/feldera_admission.py",
    "scripts/red_guard.py", "scripts/test_red_guard.py",
    "scripts/red_before.py", "scripts/test_red_before.py", "scripts/pytest-plugins.txt",
}
EVIDENCE_DIRS = {
    "test", "tests", "__tests__", "__snapshots__", "fixture", "fixtures",
    "expected", "golden", "goldens", "snapshots", "cases", "vectors", "testdata",
}
# Expectations recorded by hand outside an evidence directory, such as the slip an example
# must render.
EXPECTATIONS = {"slip.yaml"}
# Evidence data that completes a red test: a new recorded outcome, snapshot or vector, not
# code and not configuration. Only these directories hold it; a fixture, a conformance case,
# a schema, a pack, a contract or a list of what is blocked or not yet supported does not.
EVIDENCE_DATA = {".json", ".jsonl", ".yaml", ".yml", ".csv", ".txt", ".ttl", ".xml", ".snap", ".golden"}
COMPLETION_DIRS = {"expected", "snapshots", "vectors"}
NOT_EVIDENCE_DIRS = {"fixture", "fixtures", "contracts", ".github"}
NOT_EVIDENCE_TOP = {"blocked", "contracts", ".github"}
NOT_EVIDENCE_NAMES = {"not-yet.json", "pack.yaml"}
# The compiler reads these directories of a pack as its definition (DEFINITION in
# compiler/rezono_compiler/modules.py), at any depth for schema/ and rezono/. An evidence
# directory inside one of them would change the pack, not record what it should produce.
DEFINITION_DIRS = {"schema", "rezono", "facts", "labels", "messages", "rules", "calc", "icons"}
EVIDENCE_HOME_DIRS = {"test", "tests"}


def protected(path):
    p = PurePosixPath(path.lower())
    return (path in POLICY or bool(EVIDENCE_DIRS.intersection(p.parts[:-1]))
            or p.name == "conftest.py" or p.name.startswith("test_")
            or p.name.endswith(("_test.py", "_support.py", ".test.ts", ".spec.ts",
                                ".test.js", ".spec.js", ".snap", ".golden"))
            or p.name in {"frozen_baseline.py", "reference.py", "pytest.ini"} | STARTUP | EXPECTATIONS
            or p.suffix == ".pth" or p.name == "entry_points.txt"
            or any(part.endswith((".dist-info", ".egg-info")) for part in p.parts[:-1])
            or "fixture" in p.stem or p.stem.endswith(("-cases", "_cases", "-vectors", "_vectors"))
            or p.parts[0] == "blocked")


# Changes here decide whether a proof is accepted or what a role may see. Nothing downstream
# catches a mistake in them, so a reviewer reads them before they land. The checker hashes
# and encodes through rezono_canon, so that package decides as much as the checker itself.
READ_FIRST_DIRS = ("checker/rezono_checker/", "packs/std-access/", "edge/gate/src/",
                   "canon/rezono_canon/")
# In the publisher, these decide what a role reads or what the checker is handed to check
# it by; decisions/checker-and-access-review.md says what each decides.
PUBLISHER = "edge/publisher/rezono_publisher/"
READ_FIRST_FILES = {"contracts/proof.yaml", *(PUBLISHER + name for name in (
    "access.py", "calc_scope.py", "sources.py", "sweep.py", "difference.py", "batch.py",
    "publish.py", "proof.py", "views.py"))}
TEST_DIRS = {"test", "tests", "__tests__"}
READ_LABEL = "p1-read-"


def collectable(name):
    """A qualified name that pytest collects by default: test functions in Test classes."""
    *classes, function = name.split("::")
    return function.startswith("test") and all(c.startswith("Test") for c in classes)


def is_test(path):
    """A test module or a file in a test directory; fixtures and helpers elsewhere are not."""
    p = PurePosixPath(path.lower())
    return (bool(TEST_DIRS.intersection(p.parts[:-1])) or p.name == "conftest.py"
            or (p.name.startswith("test_") and p.suffix == ".py")
            or p.name.endswith(("_test.py", ".test.ts", ".spec.ts", ".test.js", ".spec.js")))


def read_first(path):
    """A changed path that a reviewer reads before the pull request lands."""
    p = path.lower()
    return (p.startswith(READ_FIRST_DIRS) or p in READ_FIRST_FILES) and not is_test(path)


def read_label(head):
    """The label that says the change at `head` has been read, or None for a malformed head."""
    if not (isinstance(head, str) and len(head) == 40
            and all(ch in "0123456789abcdef" for ch in head)):
        return None
    # The full id: a prefix is cheap to match with another commit, which would inherit the label.
    return READ_LABEL + head


def is_red(node):
    expr = node.func if isinstance(node, ast.Call) else node
    return isinstance(expr, ast.Attribute) and ast.unparse(expr) == "pytest.mark.xfail"


def mark_signature(mark):
    if isinstance(mark, ast.Call):
        mark.keywords = [kw for kw in mark.keywords if not
                         (kw.arg == "reason" and isinstance(kw.value, ast.Constant)
                          and isinstance(kw.value.value, str))]
    return ast.dump(mark)


def normalized(blob):
    """Remove mark syntax only, preserving every other source byte and each mark's location."""
    source = blob.decode("utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    spans = []

    def offset(line, col):
        # AST columns count UTF-8 bytes.
        return starts[line - 1] + len(lines[line - 1].encode()[:col].decode())

    def bounds(node):
        return offset(node.lineno, node.col_offset), offset(node.end_lineno, node.end_col_offset)

    def full_line(node, markers):
        begin = starts[node.lineno - 1]
        end = starts[node.end_lineno]
        if source[bounds(node)[1]:end].strip():
            raise ValueError("mark shares a line with other source")
        spans.append((begin, end, markers))

    def element(items, idx, markers):
        start, end = bounds(items[idx])
        if idx:
            start = bounds(items[idx - 1])[1]
        elif len(items) > 1:
            end = bounds(items[1])[0]
        spans.append((start, end, markers))

    for node in ast.walk(tree):
        for mark in getattr(node, "decorator_list", ()):
            if is_red(mark):
                full_line(mark, [mark])
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "pytestmark":
            holder = node.value
            if is_red(holder):
                full_line(node, [holder])
            elif isinstance(holder, (ast.List, ast.Tuple)):
                if holder.elts and all(is_red(v) for v in holder.elts):
                    full_line(node, holder.elts)
                else:
                    for i, mark in enumerate(holder.elts):
                        if is_red(mark):
                            element(holder.elts, i, [mark])
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "pytest.param":
            args = [*node.args, *node.keywords]
            for i, item in enumerate(args):
                if not isinstance(item, ast.keyword) or item.arg != "marks":
                    continue
                holder = item.value
                if is_red(holder):
                    element(args, i, [holder])
                elif isinstance(holder, (ast.List, ast.Tuple)):
                    if holder.elts and all(is_red(v) for v in holder.elts):
                        element(args, i, holder.elts)
                    else:
                        for j, mark in enumerate(holder.elts):
                            if is_red(mark):
                                element(holder.elts, j, [mark])
    clean = []
    signatures = Counter()
    pos = length = 0
    for start, end, markers in sorted(spans, key=lambda row: row[0]):
        if start < pos:
            raise ValueError("overlapping marks require planner review")
        clean.append(source[pos:start])
        length += start - pos
        for mark in markers:
            signatures[length, mark_signature(mark)] += 1
        pos = end
    clean.append(source[pos:])
    comments = [t.string for t in tokenize.generate_tokens(io.StringIO(source).readline)
                if t.type == tokenize.COMMENT]
    return "".join(clean), signatures, comments


def allowed(path, before, after):
    if not protected(path):
        return True
    if path in POLICY or not path.endswith(".py") or before is None or after is None:
        return False
    try:
        old, old_marks, old_comments = normalized(before)
        new, new_marks, new_comments = normalized(after)
    except (SyntaxError, ValueError, UnicodeError, tokenize.TokenError, RecursionError):
        return False
    return bool(old_marks) and old == new and old_comments == new_comments and new_marks <= old_marks


# One changed path. `before` and `after` hold inspectable bytes, or None when that
# side is absent, too large or not a regular file. `status` is Git's status letter.
Change = namedtuple("Change", "path status before after")
Inventory = namedtuple("Inventory", "owners marks tests")
EMPTY = Inventory(frozenset(), (), {})
CI_WORKFLOW = ".github/workflows/ci.yml"
LIMIT = 2_000_000
UNREADABLE = (SyntaxError, ValueError, UnicodeError, RecursionError)


# Python runs these at start-up, before pytest collects anything; a .pth file may run a line of
# code as well. setup.py is protected as well as source: it can register a pytest plugin.
STARTUP = {"sitecustomize.py", "usercustomize.py", "setup.py"}
# A package's metadata can register a pytest plugin (the `pytest11` entry point). CI installs
# the candidate, so the plugin loads and its hooks can drop a red test from the collection.
PLUGIN_CONFIG = {"pyproject.toml", "setup.cfg"}
UNREADABLE_CONFIG = b"\xff"


def plugin_config(path):
    return PurePosixPath(path.lower()).name in PLUGIN_CONFIG


def pytest_plugins(path, blob):
    """What in a pyproject.toml or setup.cfg blob can register a pytest plugin.

    That is the pytest11 entry points, and every way to give entry points from elsewhere:
    `dynamic` entry points and their source in pyproject.toml, `entry_points` under
    `[options]` in setup.cfg (`file: ...`). A blob that does not parse gives its bytes, so that
    any change to it counts. CI also compares the installed plugins with a list from the base
    (scripts/pytest-plugins.txt), which covers any other way.
    """
    if blob is None:
        return None
    try:
        text = blob.decode("utf-8")
        if PurePosixPath(path.lower()).name == "pyproject.toml":
            data = tomllib.loads(text)
            project, tool = data.get("project", {}), data.get("tool", {})
            dynamic = project.get("dynamic", [])
            return json.dumps([project.get("entry-points", {}).get("pytest11"),
                               tool.get("poetry", {}).get("plugins", {}).get("pytest11"),
                               "entry-points" in dynamic,
                               tool.get("setuptools", {}).get("dynamic", {}).get("entry-points")], sort_keys=True)
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(text)
        return json.dumps([parser.get(section, option, fallback=None) for section, option in (
            ("options.entry_points", "pytest11"), ("options", "entry_points"))])
    except (UnicodeError, tomllib.TOMLDecodeError, configparser.Error, AttributeError, TypeError, ValueError):
        return blob


def source(path):
    """A path the guard does not protect, or policy that is also source; not documentation."""
    if path in SOURCE_POLICY or PurePosixPath(path).name == "setup.py":
        return True
    return not (protected(path) or path.endswith(".md") or PurePosixPath(path).parts[0] in {"docs", "decisions"})


def is_param(node):
    return isinstance(node, ast.Call) and ast.unparse(node.func) == "pytest.param"


def red_marks(holder):
    if is_red(holder):
        return [holder]
    if isinstance(holder, (ast.List, ast.Tuple)):
        return [mark for mark in holder.elts if is_red(mark)]
    return []


class _Unmark(ast.NodeTransformer):
    """Drop red marks, as `normalized` does, so that lifting one is not a change."""

    def generic_visit(self, node):
        node = super().generic_visit(node)
        if hasattr(node, "decorator_list"):
            node.decorator_list = [d for d in node.decorator_list if not is_red(d)]
        if is_param(node):
            kept = []
            for kw in node.keywords:
                if kw.arg == "marks":
                    if is_red(kw.value):
                        continue
                    if isinstance(kw.value, (ast.List, ast.Tuple)) and kw.value.elts:
                        kw.value.elts = [v for v in kw.value.elts if not is_red(v)]
                        if not kw.value.elts:
                            continue
                kept.append(kw)
            node.keywords = kept
        return node


def inventory(blob):
    """Read the owners of red marks, each red mark with its owner, and each test function.

    An owner is the module, a class or function by qualified name, or a pytest.param
    keyed by its arguments other than `marks`. `tests` maps the qualified name of a
    test function to its syntax without red marks and whether a red mark applies to it.
    """
    tree = ast.parse(blob.decode("utf-8"))
    owners, marks, tests = {"<module>"}, [], {}
    for node in ast.walk(tree):
        if is_param(node):
            bare = copy.deepcopy(node)
            bare.keywords = [kw for kw in bare.keywords if kw.arg != "marks"]
            owner = "param " + ast.unparse(bare)
            owners.add(owner)
            for kw in node.keywords:
                if kw.arg == "marks":
                    marks.extend((owner, mark) for mark in red_marks(kw.value))

    def visit(body, scope, inherited):
        red_scope = inherited
        for node in body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "pytestmark"):
                found = red_marks(node.value)
                marks.extend((scope or "<module>", mark) for mark in found)
                red_scope = red_scope or bool(found)
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = f"{scope}::{node.name}" if scope else node.name
            owners.add(name)
            marks.extend((name, mark) for mark in node.decorator_list if is_red(mark))
            red = red_scope or any(is_red(n) for d in node.decorator_list for n in ast.walk(d))
            if isinstance(node, ast.ClassDef):
                visit(node.body, name, red)
            elif node.name.startswith("test"):
                tests[name] = (ast.dump(_Unmark().visit(copy.deepcopy(node))), red)

    visit(tree.body, "", False)
    return Inventory(owners, marks, tests)


def strict(mark):
    """A red mark that fails when its test passes, and that runs its test."""
    if not isinstance(mark, ast.Call):
        return False
    words = {kw.arg: kw.value for kw in mark.keywords}

    def true(name):
        value = words.get(name)
        return isinstance(value, ast.Constant) and value.value is True

    return None not in words and true("strict") and ("run" not in words or true("run"))


MILESTONES = ("M1: ", "M2: ", "M3: ", "M4: ", "extra: ", "later: ")


def milestone(mark):
    """A red mark whose reason is literal text that starts with a milestone."""
    if not isinstance(mark, ast.Call):
        return False
    return any(kw.arg == "reason" and isinstance(kw.value, ast.Constant)
               and isinstance(kw.value.value, str) and kw.value.value.startswith(MILESTONES)
               for kw in mark.keywords)


def rank(mark):
    """The position of a red mark's milestone, or the last position for a mark without one."""
    for kw in mark.keywords if isinstance(mark, ast.Call) else ():
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            for position, prefix in enumerate(MILESTONES):
                if kw.value.value.startswith(prefix):
                    return position
    return len(MILESTONES)


def postponed(old, new):
    """Per owner and mark without its reason, whether some mark moved to a later milestone.

    Marks keep their owner and signature when only their reasons change, so the new marks must
    fit into the old ones with each new milestone no later than the one it replaces. A mark
    without a milestone may take any milestone; a new mark without one is refused elsewhere.
    """
    def ranks(inv):
        found = {}
        for owner, mark in inv.marks:
            found.setdefault((owner, mark_signature(copy.deepcopy(mark))), []).append(rank(mark))
        return found

    old_ranks, moved = ranks(old), set()
    for key, after in ranks(new).items():
        after = sorted((r for r in after if r < len(MILESTONES)), reverse=True)
        before = sorted(old_ranks.get(key, ()), reverse=True)
        # The k-th latest new milestone may be no later than the k-th latest old one. A mark
        # beyond the old ones is new, and needs the planner label whatever its milestone.
        if any(r > b for r, b in zip(after, before)):
            moved.add(key[0])
    return sorted(moved)


def lifted_tests(before, after):
    """The test functions that a lift of red marks alone turns from red to green."""
    try:
        old, new = inventory(before), inventory(after)
    except UNREADABLE:
        return ()
    marks = lambda inv: Counter((owner, ast.dump(mark)) for owner, mark in inv.marks)
    gone, added = marks(old) - marks(new), marks(new) - marks(old)
    if sum(gone.values()) != 1 or added:
        return ()  # Exactly one mark goes, and every other mark stays as it was.
    return tuple(sorted(name for name, (_, red) in new.tests.items()
                        if not red and old.tests.get(name, (None, False))[1]))


def evidence_home(path, test_path, packs):
    """Whether the evidence directory in `path` sits where evidence lives, not a definition.

    The first expected/, snapshots/ or vectors/ directory must sit directly in a pack root
    (a directory with pack.yaml, given in `packs`), in a tests/ or test/ directory, or in a
    directory on the path of the test file. Nothing under packs/ counts, nor anything below
    a directory that the compiler reads as a pack definition.
    """
    parts = PurePosixPath(path).parts
    lower = [part.lower() for part in parts]
    at = next((i for i, part in enumerate(lower[:-1]) if part in COMPLETION_DIRS), None)
    if not at or lower[0] == "packs" or DEFINITION_DIRS.intersection(lower[:at]):
        return False
    parent = "/".join(parts[:at])
    test_dirs = PurePosixPath(test_path).parts[:-1]
    on_test_path = {"/".join(test_dirs[:k]) for k in range(1, len(test_dirs) + 1)}
    return parent in packs or lower[at - 1] in EVIDENCE_HOME_DIRS or parent in on_test_path


def new_evidence(change, test_path, packs):
    """An added regular file of evidence data under expected/, snapshots/ or vectors/.

    Only an added file: a changed one could weaken an expectation the test already holds.
    `after` is None unless Git records a regular, non-executable file (mode 100644) of
    readable size, so a symbolic link or an executable never counts.
    """
    p = PurePosixPath(change.path.lower())
    return (change.status == "A" and change.after is not None
            and protected(change.path) and change.path not in POLICY
            and p.suffix in EVIDENCE_DATA and not p.name.endswith(".schema.json")
            and p.name not in NOT_EVIDENCE_NAMES and p.parts[0] not in NOT_EVIDENCE_TOP
            and not NOT_EVIDENCE_DIRS.intersection(p.parts[:-1])
            and evidence_home(change.path, test_path, packs))


def lift_only(c):
    """The collectable tests that a change of a test file by one lifted mark turns green."""
    if not (c.status == "M" and c.path.endswith(".py") and protected(c.path) and c.path not in POLICY
            and c.before is not None and c.after is not None and allowed(c.path, c.before, c.after)):
        return ()
    return tuple(n for n in lifted_tests(c.before, c.after) if collectable(n))


def completion(changes, packs=frozenset()):
    """The (test file, test names) that a pull request completes with evidence data, or None.

    It lifts exactly one red mark, in one test file whose change is only that lift, and that
    turns at least one test that pytest collects green. Every other path is new evidence data
    (`new_evidence`). Anything else, such as source, another test file, another mark, a
    changed or removed file, means it is not an evidence completion. `packs` holds the pack
    roots at the head: the directories with a pack.yaml.
    """
    changes = list(changes)
    lifts = [(c, names) for c in changes if (names := lift_only(c))]
    if len(lifts) != 1:
        return None
    test, names = lifts[0]
    rest = [c for c in changes if c is not test]
    if not rest or not all(new_evidence(c, test.path, packs) for c in rest):
        return None
    return test.path, names


def pack_roots(rev):
    """The directories that hold a pack.yaml at `rev`, read from Git objects only."""
    names = git("ls-tree", "-r", "-z", "--name-only", "--full-tree", rev).split(b"\0")
    return frozenset(str(PurePosixPath(n.decode("utf-8", "surrogateescape")).parent)
                     for n in names if n.endswith(b"/pack.yaml"))


# A pin update: a pack that changes gets a new hash, and every pack.yaml that imports it pins
# the new one. In a fixture or test pack that is a protected change, yet it holds no
# expectation of its own. With the planner label it may come beside a lifted mark when the
# guard computes the new hash itself (decisions/fixture-pin-update.md).
# The files that make up a pack's hash, as compiler/rezono_compiler/modules.py defines them
# (DEFINITION and pack_hash); scripts/test_red_guard.py keeps the two the same.
DEFINITION = ("pack.yaml", "channels.yaml", "schema/**/*.yaml", "rezono/**/*.rezono", "rezono/**/*.json",
              "labels/*.yaml", "messages/*.mf2", "rules/*.dl", "calc/*.yaml", "sweeps.yaml", "questions.yaml",
              "views.yaml", "icons/*.svg", "icons/sources.yaml")
PIN_DIRS = {"fixture", "fixtures", "test", "tests"}
PIN = re.compile(r"sha256:[ \t]*([0-9a-f]{64})\b")
REGULAR = {"100644", "100755"}


class Tree:
    """The files of one revision: `modes` maps each path to its Git mode, `read` gives its bytes."""

    def __init__(self, modes, read):
        self.modes, self.read = modes, read

    @classmethod
    def of(cls, files):
        """A tree of regular files from {path: bytes}, for tests."""
        return cls({path: "100644" for path in files}, files.__getitem__)

    @classmethod
    def at(cls, rev):
        """The tree of a revision, read from Git objects only."""
        modes, oids = {}, {}
        for entry in filter(None, git("ls-tree", "-r", "-z", "--full-tree", rev).split(b"\0")):
            meta, raw = entry.split(b"\t", 1)
            mode, _, oid = meta.decode().split()
            path = raw.decode("utf-8", "surrogateescape")
            modes[path], oids[path] = mode, oid
        return cls(modes, lambda path: git("cat-file", "blob", oids[path]))


def definition_file(rel):
    """Whether a path relative to a pack root matches DEFINITION, as pathlib's glob does."""
    parts = rel.split("/")
    for pattern in DEFINITION:
        pp = pattern.split("/")
        if "**" not in pp:
            if len(parts) == len(pp) and all(map(fnmatchcase, parts, pp)):
                return True
            continue
        at = pp.index("**")
        head, tail = pp[:at], pp[at + 1:]
        if (len(parts) >= len(head) + len(tail) and all(map(fnmatchcase, parts[:len(head)], head))
                and all(map(fnmatchcase, parts[len(parts) - len(tail):], tail))):
            return True
    return False


def canonical_hash(files):
    """rezono_canon.canonical_sha256 of a {str: str} mapping: RFC 8785 keys in UTF-16 order."""
    text = "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + json.dumps(files[k], ensure_ascii=False)
                          for k in sorted(files, key=lambda k: k.encode("utf-16-be"))) + "}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pack_hash(tree, pack_dir):
    """The pack's hash at `tree`, or None when a file in the pack is not a regular file."""
    prefix, files = pack_dir + "/", {}
    for path, mode in tree.modes.items():
        if not path.startswith(prefix):
            continue
        if mode not in REGULAR:
            return None  # A link or a submodule: what pathlib reads there is not in the tree.
        rel = path[len(prefix):]
        if definition_file(rel):
            files[rel] = hashlib.sha256(tree.read(path)).hexdigest()
    return canonical_hash(files)


def import_pins(text):
    """{line number: (name, path, sha256)} for each pin in the imports of a pack.yaml text.

    An import is a sequence item under the top-level `imports:` key, written as a block or a
    flow mapping. Its sha256 sits on one line; an item with no or several pins is left out.
    """
    lines, pins, item, inside = text.splitlines(), {}, [], False

    def close():
        found = [i for i in item if PIN.search(lines[i])]
        body = "\n".join(lines[i] for i in item)
        name = re.search(r"\bname:[ \t]*['\"]?([a-z0-9-]+)", body)
        path = re.search(r"\bpath:[ \t]*['\"]?([^\s,}'\"]+)", body)
        if len(found) == 1 and len(PIN.findall(body)) == 1 and name and path:
            pins[found[0]] = (name.group(1), path.group(1), PIN.search(lines[found[0]]).group(1))

    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace() and not line.startswith("-"):
            if item:
                close()
            item, inside = [], bool(re.match(r"imports:[ \t]*(#.*)?$", line))
            continue
        if inside:
            if line.lstrip().startswith("-"):
                if item:
                    close()
                item = []
            item.append(i)
    if inside and item:
        close()
    return pins


def imported_dirs(tree, pack_dir, seen=None):
    """The pack directories that `pack_dir` imports at `tree`, directly or not."""
    seen = set() if seen is None else seen
    try:
        text = tree.read(pack_dir + "/pack.yaml").decode("utf-8")
    except (KeyError, UnicodeError, subprocess.CalledProcessError):
        return seen
    for _, path, _ in import_pins(text).values():
        target = posixpath.normpath(posixpath.join(pack_dir, path))
        if target not in seen and not target.startswith("../"):
            seen.add(target)
            imported_dirs(tree, target, seen)
    return seen


def pin_update(change, tree, changed):
    """Whether a change only re-pins imports of a fixture or test pack to their hash at `tree`.

    The pack.yaml exists already (status M) under a fixture or test directory. Only lines with
    `sha256: <64 hex>` in its imports differ, each only in that value, and each new value is
    the hash of the imported pack at `tree`. That pack, or one it imports, changes in this pull
    request (`changed` holds every changed path).
    """
    p = PurePosixPath(change.path)
    if not (change.status == "M" and p.name == "pack.yaml" and change.before is not None
            and change.after is not None and PIN_DIRS.intersection(part.lower() for part in p.parts[:-1])):
        return False
    try:
        before, after = change.before.decode("utf-8"), change.after.decode("utf-8")
    except UnicodeError:
        return False
    old_lines, new_lines = before.splitlines(keepends=True), after.splitlines(keepends=True)
    if len(old_lines) != len(new_lines):
        return False
    differ = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    old_pins, new_pins = import_pins(before), import_pins(after)
    if not differ:
        return False
    for i in differ:
        if (i not in old_pins or i not in new_pins or old_pins[i][:2] != new_pins[i][:2]
                or PIN.sub("", old_lines[i]) != PIN.sub("", new_lines[i])):
            return False
        _, path, digest = new_pins[i]
        target = posixpath.normpath(posixpath.join(str(p.parent), path))
        if target.startswith("../") or target + "/pack.yaml" not in tree.modes:
            return False
        if pack_hash(tree, target) != digest:
            return False
        dirs = {target} | imported_dirs(tree, target)
        if not any(c.startswith(d + "/") for d in dirs for c in changed):
            return False
    return True


def pin_updates(changes, rev):
    """The paths of the changes that are pin updates at `rev`."""
    candidates = [c for c in changes if c.status == "M" and PurePosixPath(c.path).name == "pack.yaml"
                  and protected(c.path)]
    if not candidates:
        return frozenset()
    tree, changed = Tree.at(rev), {c.path for c in changes}
    return frozenset(c.path for c in candidates if pin_update(c, tree, changed))


def review(changes, planner=False, head=None, labels=(), packs=frozenset(), pins=frozenset()):
    """Return (errors, notes) for a sequence of Change records.

    `head` and `labels` describe a pull request. Without `head`, as in the merge queue,
    labels are not read and changes to the checker or read access are not refused.
    `packs` holds the pack roots of the reviewed revision, for an evidence completion, and
    `pins` the paths whose change is a pin update (`pin_update`).
    """
    changes = list(changes)
    errors, notes, lifted, other, unread = [], [], [], [], []
    for c in changes:
        if read_first(c.path):
            unread.append(ascii(c.path))
        if c.path == CI_WORKFLOW:
            notes.append(f"CHANGED {CI_WORKFLOW}")
        if (not protected(c.path) and plugin_config(c.path)
                and pytest_plugins(c.path, c.before) != pytest_plugins(c.path, c.after)):
            other.append(ascii(c.path))
            notes.append(f"CHANGED {c.path} pytest plugins")
            if not planner:
                errors.append(f"ERROR planner label required for the pytest plugins in {ascii(c.path)}")
            continue
        if not protected(c.path):
            continue
        quoted = ascii(c.path)
        if planner and c.path in pins:
            notes.append(f"PINNED {c.path}")
            continue
        if not (c.path.endswith(".py") and allowed(c.path, c.before, c.after)):
            other.append(quoted)
            if not planner:
                errors.append(f"ERROR planner label required for {quoted}")
        if c.status == "D":
            notes.append(f"REMOVED {c.path}")
            continue
        if not c.path.endswith(".py") or c.path in POLICY:
            if c.status != "A" and c.path not in POLICY:
                notes.append(f"CHANGED {c.path}")
            continue
        if c.after is None:
            errors.append(f"ERROR cannot inspect red marks in {quoted}")
            continue
        try:
            new = inventory(c.after)
        except UNREADABLE:
            continue  # A test file that does not parse fails in CI and carries no working mark.
        try:
            old = EMPTY if c.before is None else inventory(c.before)
        except UNREADABLE:
            old = EMPTY
        signed = lambda inv: Counter((o, mark_signature(copy.deepcopy(m))) for o, m in inv.marks)
        old_marks, seen = signed(old), Counter()
        # Per owner and mark without its reason, the marks without a milestone may not grow:
        # a new mark needs one, and a changed reason keeps a milestone.
        unmarked = lambda inv: Counter((o, mark_signature(copy.deepcopy(m)))
                                       for o, m in inv.marks if not milestone(m))
        old_unmarked, new_unmarked = unmarked(old), unmarked(new)
        for owner, _ in sorted(key for key, n in new_unmarked.items() if n > old_unmarked[key]):
            errors.append(f"ERROR red mark on {ascii(c.path + '::' + owner)} needs a reason that is "
                          f"literal text starting with one of {', '.join(map(repr, MILESTONES))}; "
                          "a changed reason keeps a milestone")
        if not planner:
            for owner in postponed(old, new):
                errors.append(f"ERROR red mark on {ascii(c.path + '::' + owner)} moves to a later "
                              "milestone; only a pull request with the planner label postpones a mark")
        old_count = Counter(owner for owner, _ in old.marks)
        new_count = Counter(owner for owner, _ in new.marks)
        if any(new_count[owner] < n for owner, n in old_count.items() if owner in new.owners):
            lifted.append(quoted)
        for owner, mark in new.marks:
            key = (owner, mark_signature(copy.deepcopy(mark)))
            seen[key] += 1
            if seen[key] > old_marks[key] and not strict(mark):
                errors.append(f"ERROR new or changed red mark on {ascii(c.path + '::' + owner)} "
                              "needs strict=True and must not set run=False")
        notes.extend(f"REMOVED {c.path}::{name}" for name in old.tests if name not in new.tests)
        # Report every changed green test, whether or not the pull request also changes source:
        # weakening an expectation on its own is the change a reviewer most needs to see.
        notes.extend(f"CHANGED {c.path}::{name}" for name, (shape, red) in new.tests.items()
                     if name in old.tests and not red and old.tests[name][0] != shape)
    completed = completion(changes, packs) if planner and lifted and other else None
    if completed:
        path, names = completed
        notes.extend(f"COMPLETED {path}::{name}" for name in names)
    elif lifted and other:
        errors.append(f"ERROR red marks are lifted in {', '.join(lifted)} while protected paths "
                      f"also change: {', '.join(other)}. Lift marks in a pull request of their own, or, with the "
                      "planner label, lift one mark beside only new evidence data in expected/, snapshots/ or vectors/ "
                      "of a pack root or test directory.")
    if head is not None and unread:
        label = read_label(head)
        if label is None:
            errors.append(f"ERROR the head commit {ascii(head)} is not a full commit id, "
                          f"so no {READ_LABEL} label can apply to it")
        elif label not in labels:
            errors.append(f"ERROR the checker or read access changes in {', '.join(unread)}: a reviewer "
                          f"reads it before it lands and then sets the label {label} for the head "
                          "commit. The planner label does not replace it, and a new push needs a new label.")
    return errors, notes


def git(*args):
    return subprocess.check_output(["git", *args])


def changes(base, head):
    records = git("diff", "--raw", "--no-abbrev", "--no-renames", "-z", base, head, "--").split(b"\0")
    for header, raw_path in zip(records[::2], records[1::2]):
        path = raw_path.decode("utf-8", "surrogateescape")
        old_mode, new_mode, old_id, new_id, status = header.decode().lstrip(":").split()
        sides = [None, None]
        if protected(path) or plugin_config(path):
            # Git objects are data. Never open a path in the proposed revision.
            for i, (mode, oid) in enumerate(((old_mode, old_id), (new_mode, new_id))):
                if mode == "100644" and int(git("cat-file", "-s", oid)) <= LIMIT:
                    sides[i] = git("cat-file", "blob", oid)
                elif mode != "000000" and plugin_config(path):
                    # A link or an oversized file: not readable as metadata, so it counts as a
                    # change of its plugins (bytes that are not UTF-8).
                    sides[i] = UNREADABLE_CONFIG
        yield Change(path, status[0], *sides)


def check(base, head, planner=False, labels=None):
    """Review base..head. With `labels`, head is the head commit of a pull request."""
    pr_head = None
    if labels is not None:
        pr_head = git("rev-parse", "--verify", "--end-of-options", head + "^{commit}").decode().strip()
    records = list(changes(base, head))
    pins = pin_updates(records, head) if planner else frozenset()
    return review(records, planner, pr_head, labels or (), pack_roots(head), pins)


def label_list(text):
    """Parse a JSON array of label names."""
    names = json.loads(text)
    if not (isinstance(names, list) and all(isinstance(name, str) for name in names)):
        raise argparse.ArgumentTypeError("labels must be a JSON array of strings")
    return names


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planner", action="store_true", help="the pull request carries the planner label")
    parser.add_argument("--labels", type=label_list,
                        help="the labels of the pull request whose head commit is `head`, as a JSON "
                             "array of names; omitted in the merge queue, where labels are not read")
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    errors, notes = check(args.base, args.head, args.planner, args.labels)
    for line in notes + errors:
        print(line)
    sys.exit(bool(errors))
