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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--counts",
        action="store_true",
        help="Print per-folder counts of red, blocked, and to-port items.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument("--skips", nargs="+", metavar="JUNIT_XML",
                        help="Count actual skipped tests per reason from pytest reports.")
    args = parser.parse_args()
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
        print(json.dumps([asdict(item) for item in items], indent=2))
        return 0
    for item in items:
        print(f"{item.id}\t{item.reason}\t{item.run_command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
