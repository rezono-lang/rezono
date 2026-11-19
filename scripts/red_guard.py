"""Read two Git trees as data and review changes to test evidence.

Without the planner label, only existing pytest xfail marks may be lifted or explained.
With it, protected paths may change, but a lifted mark must stand alone and every added
or changed mark must be strict. Either way, the reason of every added or changed mark is
literal text that starts with a milestone, and a changed reason keeps the milestone it had.
Removed and changed evidence is reported either way.
"""
import argparse
import ast
from collections import Counter, namedtuple
import copy
import io
from pathlib import PurePosixPath
import subprocess
import sys
import tokenize


# The merge queue runs a candidate's own workflow files, so the workflows that define the
# required checks (`check` and `Light checks` in ci.yml, and the reusable cluster workflow
# that `check` aggregates) are policy as much as the guard that reviews them.
POLICY = {
    ".github/workflows/red-policy.yml",
    ".github/workflows/ci.yml", ".github/workflows/disposable-cluster.yml",
    ".github/workflows/resume-feldera-review.yml", "scripts/feldera_admission.py",
    "scripts/red_guard.py", "scripts/test_red_guard.py",
    "scripts/red_before.py", "scripts/test_red_before.py",
}
EVIDENCE_DIRS = {
    "test", "tests", "__tests__", "__snapshots__", "fixture", "fixtures",
    "expected", "golden", "goldens", "snapshots", "cases", "vectors", "testdata",
}


def protected(path):
    p = PurePosixPath(path.lower())
    return (path in POLICY or bool(EVIDENCE_DIRS.intersection(p.parts[:-1]))
            or p.name == "conftest.py" or p.name.startswith("test_")
            or p.name.endswith(("_test.py", "_support.py", ".test.ts", ".spec.ts",
                                ".test.js", ".spec.js", ".snap", ".golden"))
            or p.name in {"frozen_baseline.py", "reference.py", "pytest.ini"}
            or "fixture" in p.stem or p.stem.endswith(("-cases", "_cases", "-vectors", "_vectors"))
            or p.parts[0] == "blocked")


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


def source(path):
    """A path the guard does not protect and that is not documentation."""
    return not (protected(path) or path.endswith(".md")
                or PurePosixPath(path).parts[0] in {"docs", "decisions"})


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


def review(changes, planner=False):
    """Return (errors, notes) for a sequence of Change records."""
    errors, notes, lifted, other = [], [], [], []
    for c in changes:
        if c.path == CI_WORKFLOW:
            notes.append(f"CHANGED {CI_WORKFLOW}")
        if not protected(c.path):
            continue
        quoted = ascii(c.path)
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
        # a new mark needs one, and a changed reason keeps the milestone it had.
        unmarked = lambda inv: Counter((o, mark_signature(copy.deepcopy(m)))
                                       for o, m in inv.marks if not milestone(m))
        old_unmarked, new_unmarked = unmarked(old), unmarked(new)
        for owner, _ in sorted(key for key, n in new_unmarked.items() if n > old_unmarked[key]):
            errors.append(f"ERROR red mark on {ascii(c.path + '::' + owner)} needs a reason that is "
                          f"literal text starting with one of {', '.join(map(repr, MILESTONES))}; "
                          "a changed reason keeps the milestone it had")
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
    if lifted and other:
        errors.append(f"ERROR red marks are lifted in {', '.join(lifted)} while protected paths "
                      f"also change: {', '.join(other)}. Lift marks in a pull request of their own.")
    return errors, notes


def git(*args):
    return subprocess.check_output(["git", *args])


def changes(base, head):
    records = git("diff", "--raw", "--no-abbrev", "--no-renames", "-z", base, head, "--").split(b"\0")
    for header, raw_path in zip(records[::2], records[1::2]):
        path = raw_path.decode("utf-8", "surrogateescape")
        old_mode, new_mode, old_id, new_id, status = header.decode().lstrip(":").split()
        sides = [None, None]
        if protected(path):
            # Git objects are data. Never open a path in the proposed revision.
            for i, (mode, oid) in enumerate(((old_mode, old_id), (new_mode, new_id))):
                if mode == "100644" and int(git("cat-file", "-s", oid)) <= LIMIT:
                    sides[i] = git("cat-file", "blob", oid)
        yield Change(path, status[0], *sides)


def check(base, head, planner=False):
    return review(list(changes(base, head)), planner)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planner", action="store_true", help="the pull request carries the planner label")
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    errors, notes = check(args.base, args.head, args.planner)
    for line in notes + errors:
        print(line)
    sys.exit(bool(errors))
