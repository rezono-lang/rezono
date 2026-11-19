"""Compare references to missing pages under docs/ with a per-page budget that may only fall."""

import argparse
import json
import posixpath
import re
import subprocess
from pathlib import Path

BUDGET = "scripts/docs-link-budget.json"
URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s<>()\[\]{}\"'`]+")
# A link into this repository through its forge still names one of its own pages.
OWN_URL = re.compile(
    r"https?://(?:github\.com/rezono-lang/rezono/(?:blob|tree|raw)/[^/]+|"
    r"raw\.githubusercontent\.com/rezono-lang/rezono/[^/]+)/(docs/[\w./+-]+)"
)
# `docs/` at the start of a path, alone or after `./` and `../` steps; not inside a longer path.
REFERENCE = re.compile(r"(?<![\w./+-])((?:\.\.?/)*)(docs/[\w./+-]*[\w+-])")


def references(path, text):
    """Yield the repository paths under docs/ that one tracked file names."""
    for match in URL.finditer(text):
        own = OWN_URL.match(match.group())
        if own:
            yield own.group(1).rstrip("/.")
    text = URL.sub(" ", text)
    for match in REFERENCE.finditer(text):
        steps, target = match.groups()
        if steps:
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), steps + target))
        if target.startswith("docs/"):
            yield target


def scan(root=Path(".")):
    """Count, per missing page under docs/, the references in tracked text files."""
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    tracked = set(filter(None, names))
    folders = {"/".join(name.split("/")[:depth]) for name in tracked for depth in range(1, name.count("/") + 1)}
    found = {}
    for name in sorted(tracked - {BUDGET}):
        path = root / name
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        for target in references(name, data.decode("utf-8", errors="replace")):
            if target not in tracked and target not in folders:
                found[target] = found.get(target, 0) + 1
    return dict(sorted(found.items()))


def read_budget(data):
    budget = json.loads(data)
    if not isinstance(budget, dict):
        raise ValueError("Expected an object of per-page reference counts")
    for page, number in budget.items():
        if not page.startswith("docs/"):
            raise ValueError(f"Budget names a path outside docs/: {page}")
        if type(number) is not int or number <= 0:
            raise ValueError("Reference counts must be positive integers")
    return budget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="commit whose budget the current budget may not exceed")
    args = parser.parse_args()
    actual = scan()
    budget = read_budget(Path(BUDGET).read_bytes())
    previous = budget
    if args.base:
        tree = subprocess.check_output(["git", "ls-tree", args.base, "--", BUDGET])
        if tree:
            previous = read_budget(subprocess.check_output(["git", "show", f"{args.base}:{BUDGET}"]))
    failed = False
    for page in sorted(set(actual) | set(budget)):
        number, limit = actual.get(page, 0), budget.get(page, 0)
        if limit > previous.get(page, 0):
            print(f"{page}: listed={limit} exceeds the base budget {previous.get(page, 0)}")
            failed = True
        if number > limit:
            print(f"{page}: observed={number} listed={limit}; the page does not exist, so add it or drop the reference")
            failed = True
        elif number < limit:
            print(f"{page}: observed={number} listed={limit}; lower the budget in {BUDGET}")
    print(f"missing_pages={len(actual)} references={sum(actual.values())}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
