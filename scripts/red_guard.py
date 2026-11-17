"""Compare marked pytest functions on two Git revisions."""
import argparse
import ast
import subprocess
import sys

from red_list import _is_xfail_call, _param_xfails


def git(*args):
    return subprocess.check_output(["git", *args]).decode("utf-8")


def snapshot(revision, path):
    tree = git("ls-tree", revision, "--", path)
    if not tree:
        return {}
    source = git("show", f"{revision}:{path}")
    functions = {}

    def walk(body, parents):
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, (*parents, node.name))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
                continue
            name = ".".join((*parents, node.name))
            marks = {}
            decorators = []
            for dec in node.decorator_list:
                if _is_xfail_call(dec):
                    marks["function"] = signature(dec)
                    continue
                if _param_xfails(dec):
                    for param_index, param in enumerate(dec.args[1].elts):
                        if not isinstance(param, ast.Call):
                            continue
                        for kw in list(param.keywords):
                            if kw.arg != "marks":
                                continue
                            seq = isinstance(kw.value, (ast.List, ast.Tuple))
                            values = kw.value.elts if seq else [kw.value]
                            keep = []
                            for index, mark in enumerate(values):
                                if _is_xfail_call(mark):
                                    marks[(len(decorators), param_index, index)] = signature(mark)
                                else:
                                    keep.append(mark)
                            if not keep:
                                param.keywords.remove(kw)
                            elif seq:
                                kw.value.elts = keep
                decorators.append(dec)
            node.decorator_list = decorators
            functions[name] = (ast.dump(node), marks)
    walk(ast.parse(source).body, ())
    return functions


def signature(call):
    call.keywords = [kw for kw in call.keywords if not (
        kw.arg == "reason" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)
    )]
    return ast.dump(call)


def check(base, head):
    changed = git("diff", "--no-renames", "--name-only", "-z", base, head).split("\0")
    errors = []
    for path in filter(None, changed):
        name = path.rsplit("/", 1)[-1]
        if not (name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py")):
            continue
        before, after = snapshot(base, path), snapshot(head, path)
        for key in before.keys() | after.keys():
            old, marks = before.get(key, (None, {}))
            new, remaining = after.get(key, (None, {}))
            if (marks and old != new) or any(marks.get(k) != v for k, v in remaining.items()):
                errors.append(f"{path}::{key}")
    return sorted(errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    issues = check(args.base, args.head)
    for issue in issues:
        print(f"ERROR planner label required for {issue}")
    sys.exit(int(bool(issues)))
