"""Read two Git trees as data; allow only existing pytest xfail marks to be lifted or explained."""
import argparse
import ast
from collections import Counter
import io
from pathlib import PurePosixPath
import subprocess
import sys
import tokenize


POLICY = {
    ".github/workflows/red-policy.yml",
    "scripts/red_guard.py", "scripts/test_red_guard.py",
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


def git(*args):
    return subprocess.check_output(["git", *args])


def check(base, head):
    records = git("diff", "--raw", "--no-abbrev", "--no-renames", "-z", base, head, "--").split(b"\0")
    errors = []
    for header, raw_path in zip(records[::2], records[1::2]):
        path = raw_path.decode("utf-8", "surrogateescape")
        if not protected(path):
            continue
        old_mode, new_mode, old_id, new_id, _ = header.decode().lstrip(":").split()
        # Git objects are data. Never open a path in the proposed revision.
        regular_python = old_mode == new_mode == "100644" and path.endswith(".py") and path not in POLICY
        if regular_python:
            sizes = (int(git("cat-file", "-s", oid)) for oid in (old_id, new_id))
            if max(sizes) <= 2_000_000:
                if allowed(path, git("cat-file", "blob", old_id), git("cat-file", "blob", new_id)):
                    continue
        errors.append(path)
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    failures = check(args.base, args.head)
    for path in failures:
        print("ERROR planner label required for", ascii(path))
    sys.exit(bool(failures))
