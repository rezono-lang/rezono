#!/usr/bin/env python3
"""Query expected-red test marks, blocked test files, and tests waiting for a planner."""

from __future__ import annotations

from collections import Counter
import xml.etree.ElementTree as ET

import argparse
import ast
import json
import re
import signal
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from components import SKIP_DIRS, discover_components  # noqa: E402


@dataclass(frozen=True)
class RedTest:
    id: str
    folder: str
    file: str
    func: str
    param: str | None
    nodeid: str
    reason: str
    strict: bool
    run_command: str


def _safe_branch_part(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return cleaned or "param"


def _is_xfail_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call):
        target = node.func
    else:
        return None
    # Match pytest.mark.xfail(...) or mark.xfail(...) or xfail(...)
    if isinstance(target, ast.Name) and target.id == "xfail":
        return node
    if isinstance(target, ast.Attribute) and target.attr == "xfail":
        return node
    return None


def _extract_xfail_meta(call: ast.Call) -> tuple[str, bool]:
    reason = ""
    strict = False
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        reason = call.args[0].value
    for kw in call.keywords:
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            reason = kw.value.value
        elif kw.arg == "strict" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, bool):
            strict = kw.value.value
    return reason, strict


def _is_pytest_param_call(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.Call):
        return None
    target = node.func
    if isinstance(target, ast.Attribute) and target.attr == "param":
        return node
    if isinstance(target, ast.Name) and target.id == "param":
        return node
    return None


def _param_label(call: ast.Call, index: int) -> str:
    for kw in call.keywords:
        if kw.arg == "id" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    parts: list[str] = []
    for arg in call.args:
        if isinstance(arg, ast.Constant):
            parts.append(str(arg.value))
        else:
            parts.append(f"arg{index}")
    return "-".join(parts) if parts else f"param{index}"


def _param_xfails(decorator: ast.AST) -> list[tuple[str, str, bool]]:
    """Extract (param_id, reason, strict) from @pytest.mark.parametrize(..., [pytest.param(..., marks=...)])."""
    if not isinstance(decorator, ast.Call):
        return []
    target = decorator.func
    if not (isinstance(target, ast.Attribute) and target.attr == "parametrize"):
        return []
    if len(decorator.args) < 2:
        return []
    values = decorator.args[1]
    if not isinstance(values, (ast.List, ast.Tuple)):
        return []
    results: list[tuple[str, str, bool]] = []
    for idx, elt in enumerate(values.elts):
        pcall = _is_pytest_param_call(elt)
        if pcall is None:
            continue
        for kw in pcall.keywords:
            if kw.arg != "marks":
                continue
            candidates = (
                kw.value.elts
                if isinstance(kw.value, (ast.List, ast.Tuple))
                else [kw.value]
            )
            for cand in candidates:
                xcall = _is_xfail_call(cand)
                if xcall is not None:
                    reason, strict = _extract_xfail_meta(xcall)
                    results.append((_param_label(pcall, idx), reason, strict))
    return results


def _format_run_command(nodeid: str) -> str:
    if any(ch in nodeid for ch in "[]() '\""):
        return f'python -m pytest "{nodeid}"'
    return f"python -m pytest {nodeid}"


def read_blocked(root: Path = ROOT) -> list[tuple[str, str]]:
    """Return (target_relpath, error_line) pairs from blocked/*.txt."""
    blocked_dir = root / "blocked"
    if not blocked_dir.is_dir():
        return []
    items: list[tuple[str, str]] = []
    for entry in sorted(blocked_dir.glob("*.txt"), key=lambda p: p.name):
        if not entry.is_file():
            continue
        line = entry.read_text(encoding="utf-8").splitlines()[0].strip()
        if ":" in line:
            target, reason = line.split(":", 1)
            items.append((target.strip(), reason.strip()))
        elif line:
            items.append((line, ""))
    return items


def read_to_port(root: Path = ROOT) -> list[tuple[str, str]]:
    """Return (target_folder, file_relpath) pairs from to-port/*.md."""
    tp_dir = root / "to-port"
    if not tp_dir.is_dir():
        return []
    items: list[tuple[str, str]] = []
    for entry in sorted(tp_dir.glob("*.md"), key=lambda p: p.name):
        if entry.name == "AGENTS.md":
            continue
        if not entry.is_file():
            continue
        folder = ""
        for line in entry.read_text(encoding="utf-8").splitlines():
            if line.startswith("Target-folder:"):
                folder = line.split(":", 1)[1].strip()
                break
        items.append((folder, entry.relative_to(root).as_posix()))
    return items


def _folder_for_path(relpath: str, folders: list[str]) -> str:
    matches = [f for f in folders if relpath == f or relpath.startswith(f + "/")]
    if matches:
        # Pick the most specific component folder if nested.
        return max(matches, key=len)
    return relpath.split("/", 1)[0]


def iter_python_test_files(root: Path = ROOT, include_blocked: bool = False) -> list[Path]:
    blocked_paths = set() if include_blocked else {target for target, _ in read_blocked(root)}
    files: list[Path] = []

    def walk(current: Path) -> None:
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            if child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if child.is_dir():
                walk(child)
            elif child.is_file() and (
                child.name.startswith("test_") or child.name.endswith("_test.py")
            ) and child.suffix == ".py":
                rel = child.relative_to(root).as_posix()
                if rel not in blocked_paths:
                    files.append(child)

    walk(root)
    return files


def extract_red_tests_from_source(
    source: str, relpath: str, folders: list[str]
) -> list[RedTest]:
    tree = ast.parse(source, filename=relpath)
    folder = _folder_for_path(relpath, folders)
    found: list[RedTest] = []

    def visit_func(fn: ast.FunctionDef | ast.AsyncFunctionDef, class_prefix: list[str]) -> None:
        if not fn.name.startswith("test"):
            return
        qual_parts = [*class_prefix, fn.name]
        qual_node = "::".join(qual_parts)
        qual_id = "--".join(qual_parts)

        for dec in fn.decorator_list:
            xcall = _is_xfail_call(dec)
            if xcall is not None:
                reason, strict = _extract_xfail_meta(xcall)
                nodeid = f"{relpath}::{qual_node}"
                found.append(
                    RedTest(
                        id=f"{relpath}--{qual_id}",
                        folder=folder,
                        file=relpath,
                        func=qual_node,
                        param=None,
                        nodeid=nodeid,
                        reason=reason,
                        strict=strict,
                        run_command=_format_run_command(nodeid),
                    )
                )
            for param_id, reason, strict in _param_xfails(dec):
                nodeid = f"{relpath}::{qual_node}[{param_id}]"
                safe_param = _safe_branch_part(param_id)
                found.append(
                    RedTest(
                        id=f"{relpath}--{qual_id}--{safe_param}",
                        folder=folder,
                        file=relpath,
                        func=qual_node,
                        param=param_id,
                        nodeid=nodeid,
                        reason=reason,
                        strict=strict,
                        run_command=_format_run_command(nodeid),
                    )
                )

    def visit_body(stmts: list[ast.stmt], class_prefix: list[str]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit_func(stmt, class_prefix)
            elif isinstance(stmt, ast.ClassDef):
                visit_body(stmt.body, [*class_prefix, stmt.name])

    visit_body(tree.body, [])
    return found


def collect_red_tests(root: Path = ROOT) -> list[RedTest]:
    folders = [c.folder for c in discover_components(root)]
    items: list[RedTest] = []
    for path in iter_python_test_files(root):
        relpath = path.relative_to(root).as_posix()
        items.extend(
            extract_red_tests_from_source(
                path.read_text(encoding="utf-8"), relpath, folders
            )
        )
    return sorted(items, key=lambda r: r.id)


def compute_counts(root: Path = ROOT) -> list[dict[str, int | str]]:
    folders = [c.folder for c in discover_components(root)]
    counts: dict[str, dict[str, int]] = {
        f: {"red": 0, "blocked": 0, "to_port": 0} for f in folders
    }
    for item in collect_red_tests(root):
        counts.setdefault(item.folder, {"red": 0, "blocked": 0, "to_port": 0})["red"] += 1
    for target, _ in read_blocked(root):
        folder = _folder_for_path(target, folders)
        counts.setdefault(folder, {"red": 0, "blocked": 0, "to_port": 0})["blocked"] += 1
    for folder, _ in read_to_port(root):
        if folder:
            counts.setdefault(folder, {"red": 0, "blocked": 0, "to_port": 0})["to_port"] += 1

    rows: list[dict[str, int | str]] = []
    for folder in sorted(counts):
        c = counts[folder]
        rows.append(
            {
                "folder": folder,
                "red": c["red"],
                "blocked": c["blocked"],
                "to_port": c["to_port"],
            }
        )
    return rows


MILESTONES = ("M1", "M2", "M3", "M4", "extra", "later")
UNMARKED = "none"


def milestone_of(reason: str) -> str:
    """Return the milestone mark a reason starts with, or ``none`` without one."""
    for mark in MILESTONES:
        if reason.startswith(f"{mark}: "):
            return mark
    return UNMARKED


def milestone_counts(items: list[RedTest]) -> dict[str, dict[str, int]]:
    """Count red tests per folder and milestone mark, including the unmarked ones."""
    columns = (*MILESTONES, UNMARKED)
    counts: dict[str, dict[str, int]] = {}
    for item in items:
        row = counts.setdefault(item.folder, dict.fromkeys(columns, 0))
        row[milestone_of(item.reason)] += 1
    return {folder: counts[folder] for folder in sorted(counts)}


def format_milestones(counts: dict[str, dict[str, int]]) -> str:
    """Render the milestone counts as a Markdown table with a total row and column."""
    columns = (*MILESTONES, UNMARKED)
    lines = [
        "| folder | " + " | ".join(columns) + " | total |",
        "| --- |" + " ---: |" * (len(columns) + 1),
    ]
    totals = dict.fromkeys(columns, 0)
    for folder, row in counts.items():
        for column in columns:
            totals[column] += row[column]
        cells = [str(row[column]) for column in columns]
        lines.append(f"| {folder} | " + " | ".join(cells) + f" | {sum(row.values())} |")
    cells = [str(totals[column]) for column in columns]
    lines.append("| total | " + " | ".join(cells) + f" | {sum(totals.values())} |")
    return "\n".join(lines)


WAIT_START = re.compile(r"\b(?:waits for|depends on)\s+", re.IGNORECASE)
CLAUSE_END = re.compile(r"[:;(]|\.(?:\s|$)")
PARENTHETICAL = re.compile(r"\s*\([^()]*\)")
TEST_NAME = re.compile(r"(?:[\w.-]+/)*test_\w*(?:\.py)?(?:(?:::|--)\w+)*")
FUNCTION_IN_LAST_FILE = re.compile(r"(?:::|--)test_\w*")
LIST_SEPARATOR =re.compile(r",|\s+and\s+")
LEADING_WORDS = frozenset({"and", "for", "or", "on", "both", "also"})
QUALIFIER_WORDS = frozenset({
    "which", "whose", "while", "that", "who", "where", "because", "so", "as",
    "until", "once", "when", "since",
})


def _wait_clauses(reason: str) -> list[str]:
    """Return the text after each "Waits for" or "Depends on", up to the end of its sentence.

    A closed parenthetical, such as "(compare_as in the rule IR)" after a test name, is left
    out, so the list goes on after it; an unclosed one ends the clause.
    """
    starts = list(WAIT_START.finditer(reason))
    clauses: list[str] = []
    for index, match in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(reason)
        rest = reason[match.end():stop]
        while (stripped := PARENTHETICAL.sub("", rest)) != rest:
            rest = stripped
        end = CLAUSE_END.search(rest)
        clauses.append(rest[: end.start()] if end else rest)
    return clauses


def wait_names(reason: str) -> tuple[list[str], bool]:
    """Return the test names a reason waits for, and whether it also waits for something else.

    A clause lists its prerequisites separated by commas and "and". An item that starts
    with a test function or test file name names a test; words after the name qualify it.
    An item that starts with a relative word ("which", "while", ...) ends the list. Any
    other item names a prerequisite that is not a test.
    """
    names: list[str] = []
    other = False
    for clause in _wait_clauses(reason):
        for item in LIST_SEPARATOR.split(clause):
            words = item.replace("`", "").split()
            while words and words[0].lower() in LEADING_WORDS:
                words.pop(0)
            if not words:
                continue
            if words[0].lower() in QUALIFIER_WORDS:
                break
            token = words[0].rstrip(".,")
            last_file = re.split(r"::|--", names[-1], maxsplit=1)[0] if names else ""
            if FUNCTION_IN_LAST_FILE.fullmatch(token) and ("/" in last_file or last_file.endswith(".py")):
                # "a/test_x.py--test_one, --test_two" names test_two in the same file.
                token = last_file + token
            if TEST_NAME.fullmatch(token):
                if token not in names:
                    names.append(token)
            else:
                other = True
    return names, other


def functions_from_source(source: str, relpath: str) -> set[str]:
    """Return the names of the test functions a test file defines, also inside classes."""
    names: set[str] = set()

    def visit(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if stmt.name.startswith("test"):
                    names.add(stmt.name)
            elif isinstance(stmt, ast.ClassDef):
                visit(stmt.body)

    visit(ast.parse(source, filename=relpath).body)
    return names


@dataclass(frozen=True)
class KnownTests:
    """The discoverable test files and functions, and which of them are red."""

    files: frozenset[str]
    tests: frozenset[tuple[str, str]]
    red: frozenset[tuple[str, str]]

    @classmethod
    def from_sources(cls, sources: dict[str, str], red_items: list[RedTest]) -> KnownTests:
        tests = {
            (relpath, name)
            for relpath, source in sources.items()
            for name in functions_from_source(source, relpath)
        }
        red = {(item.file, item.func.rsplit("::", 1)[-1]) for item in red_items}
        return cls(frozenset(sources), frozenset(tests), frozenset(red))

    def is_green(self, name: str) -> bool:
        """A named test is green when it exists and is not red; a file when none of its tests is red.

        A name with a slash or a ``.py`` suffix is a file path; a bare name is a test function
        or the stem of a test file. A path may name one function after ``::`` or, as in the id
        this script prints, after ``--``. A name that matches nothing is not green.
        """
        path, *parts = re.split(r"::|--", name)
        funcs = [part for part in parts if part.startswith("test")]
        func = funcs[-1] if funcs else ""
        if "/" in path or path.endswith(".py"):
            target = path if path.endswith(".py") else f"{path}.py"
            if func:
                files: set[str] = set()
                tests = {test for test in self.tests if test == (target, func)}
            else:
                files = {target} & self.files
                tests = set()
        else:
            files = {f for f in self.files if f.rsplit("/", 1)[-1] == f"{path}.py"}
            tests = {test for test in self.tests if test[1] == path}
        if not files and not tests:
            return False
        if any(test in self.red for test in tests):
            return False
        return not any(red_file in files for red_file, _ in self.red)


def wait_status(reason: str, index: KnownTests) -> dict[str, object]:
    """Return ``{"ready": True}``, or ``{"waits": [...]}`` with the named tests that are not green.

    ``waits`` without a name means the reason waits for something that is not a test.
    """
    names, other = wait_names(reason)
    waiting = [name for name in names if not index.is_green(name)]
    if waiting or other:
        return {"waits": waiting}
    return {"ready": True}


def load_test_sources(root: Path = ROOT) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in iter_python_test_files(root)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--counts",
        action="store_true",
        help="Print per-folder counts of red, blocked, and to-port items.",
    )
    parser.add_argument(
        "--milestones",
        action="store_true",
        help="Print per-folder counts of red tests per milestone mark; 'none' counts reasons without one.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument("--skips", nargs="+", metavar="JUNIT_XML",
                        help="Count actual skipped tests per reason from pytest reports.")
    parser.add_argument("--all-tests-blocked", metavar="COMPONENT",
                        help="Validate the sole exception to pytest exit code five.")
    args = parser.parse_args()
    if args.all_tests_blocked:
        directory = (ROOT / args.all_tests_blocked).resolve()
        if not directory.is_dir() or not directory.is_relative_to(ROOT):
            return 1
        files = {path.relative_to(ROOT).as_posix() for path in
                 iter_python_test_files(directory, include_blocked=True)}
        blocked = {target for target, _ in read_blocked()}
        missing = sorted(files - blocked)
        if not files or missing:
            print("ERROR no discoverable test files or missing blocked entries:", missing)
            return 1
        print(f"All {len(files)} test files have individual blocked entries.")
        return 0
    if args.skips:
        counts: Counter[str] = Counter()
        oracle_cases = []
        for report in args.skips:
            suite = ET.parse(report)
            for case in suite.iter("testcase"):
                name = case.get("name", "")
                if "souffle" in name.lower() and not any(
                    case.find(tag) is not None for tag in ("skipped", "failure", "error")
                ):
                    oracle_cases.append(name)
            for skip in suite.iter("skipped"):
                if skip.get("type") != "pytest.xfail":
                    counts[skip.get("message", "unspecified")] += 1
        if args.json:
            print(json.dumps(dict(sorted(counts.items()))))
        else:
            for reason, count in sorted(counts.items()):
                print(f"{count} skipped: {reason}")
            print(f"Total skipped: {sum(counts.values())}")
            if oracle_cases:
                print(f"Passed tests naming the Souffle oracle: {len(oracle_cases)}")
                print(f"Example: {sorted(oracle_cases)[0]}")
        return 0

    if args.milestones:
        milestones = milestone_counts(collect_red_tests())
        if args.json:
            print(json.dumps(milestones, indent=2))
        else:
            print(format_milestones(milestones))
        return 0

    if args.counts:
        rows = compute_counts()
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        print("folder\tred\tblocked\tto-port")
        tot_r = tot_b = tot_p = 0
        for row in rows:
            r = int(row["red"])
            b = int(row["blocked"])
            p = int(row["to_port"])
            tot_r += r
            tot_b += b
            tot_p += p
            print(f"{row['folder']}\t{r}\t{b}\t{p}")
        print(f"total\t{tot_r}\t{tot_b}\t{tot_p}")
        return 0

    items = collect_red_tests()
    if args.json:
        index = KnownTests.from_sources(load_test_sources(), items)
        print(json.dumps(
            [asdict(item) | wait_status(item.reason, index) for item in items], indent=2
        ))
        return 0
    for item in items:
        print(f"{item.id}\t{item.reason}\t{item.run_command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
