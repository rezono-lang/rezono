"""Compare tracked file contents and names with the per-file disclosure budget.

The budget is a ceiling per file and kind that may only fall: more findings than listed, or a listed number
above the base budget, is red. Fewer findings than listed is green with a hint to lower the budget, so two
changes that each remove a finding from the same file stay green when they are merged together.
"""

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

BUDGET = "scripts/leak-budget.json"
EMAIL = re.compile(rb"(?:(?:\d+\+)?[\w-]+\[bot\]|[\w.!#$%&'*+/=?^_\x60{|}~-]+)@(?:[\w-]+\.)+[a-zA-Z]{2,}")
AUTHOR = b"222310762+vdo89" + b"@users.noreply.github.com"
BOT = re.compile(rb"(?:\d+\+)?[\w-]+\[bot\]@users\.noreply\.github\.com")
EXAMPLE = re.compile(rb"(?:[\w-]+\.)*(?:example\.(?:com|org|net)|example|invalid|test|localhost)")
PATTERNS = {
    "machine_path": re.compile(rb"(?:[A-Z]:[/\\]+(?:Users|Documents and Settings)[/\\]+|/(?:Users|home)/|/mnt/[a-z]/Users/)[\w.-]+", re.I),
    "ticket": re.compile(rb"RV-[A-Z]*[0-9]+"),
    "old_name": re.compile(rb"(?<![A-Za-z0-9])(?:re[d]e\.dev|re[d]e|rec[k]on|a[t]las)(?![A-Za-z0-9])", re.I),
}
# A pull request's branch name stays visible after it lands. The names of internal work streams do not
# belong in it: not followed by a number (`kern-67-error-codes`, `golf-1`), and not as a segment of their
# own (`planner-kern-std-table`). A name that carries a repository path (`task/<test>`, `fix/<path>`,
# `note/<test>`) is held to the first rule only, since paths such as `examples/platform/` and
# `decisions/run-*.md` hold such a word as a segment.
STREAMS = ("kern", "taal", "kring", "platform", "run")
NUMBERED_STREAM = re.compile(r"(?<![a-z0-9])(?:golf|kern|taal|kring|platform|run)-[0-9]", re.I)
PATH_BRANCHES = ("task/", "fix/", "note/")


def counts(data):
    found = {name: sum(1 for _ in pattern.finditer(data)) for name, pattern in PATTERNS.items()}
    emails = (m.group() for m in EMAIL.finditer(data))
    found["email"] = sum(
        address != AUTHOR and not BOT.fullmatch(address) and not EXAMPLE.fullmatch(address.split(b"@")[-1].lower())
        for address in emails
    )
    return {kind: number for kind, number in sorted(found.items()) if number}


def branch_finding(name):
    """Why a pull request's branch name is refused, or None."""
    if NUMBERED_STREAM.search(name):
        return "numbered_stream"
    if not name.startswith(PATH_BRANCHES) and set(STREAMS) & {part.lower() for part in re.split(r"[/-]", name)}:
        return "stream_segment"
    return None


def scan():
    paths = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")
    result = {}
    for raw in filter(None, paths):
        name = raw.decode("utf-8")
        path = Path(name)
        data = str(path.readlink()).encode() if path.is_symlink() else path.read_bytes()
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            data = data.decode("utf-16", errors="replace").encode()
        findings = counts(raw + b"\n" + data)
        if findings:
            result[name] = findings
    return result


def read_budget(data):
    budget = json.loads(data)
    if not isinstance(budget, dict):
        raise ValueError("Expected an object of per-file exception counts")
    kinds = {"email", *PATTERNS}
    for entry in budget.values():
        if not isinstance(entry, dict) or not entry or not entry.keys() <= kinds:
            raise ValueError("Invalid exception categories")
        if any(type(number) is not int or number <= 0 for number in entry.values()):
            raise ValueError("Exception counts must be positive integers")
    return budget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--branch", default=os.environ.get("LEAK_CHECK_BRANCH"),
                        help="head branch of the pull request, whose name is checked too")
    args = parser.parse_args()
    actual = scan()
    budget = read_budget(Path(BUDGET).read_bytes())
    previous = budget
    if args.base:
        tree = subprocess.check_output(["git", "ls-tree", args.base, "--", BUDGET])
        if tree:
            previous = read_budget(subprocess.check_output(["git", "show", f"{args.base}:{BUDGET}"]))
    finding = branch_finding(args.branch) if args.branch else None
    if finding:
        print(f"branch {args.branch}: {finding}; name the branch after its subject, as fix/<path> or task/<test>")
    failed = finding is not None
    totals = Counter()
    for path in sorted(set(actual) | set(budget)):
        observed, allowed = actual.get(path, {}), budget.get(path, {})
        totals.update(observed)
        for kind in sorted(set(observed) | set(allowed)):
            number, limit = observed.get(kind, 0), allowed.get(kind, 0)
            # Print counts only, including when a filename itself contains a finding.
            label = "[redacted filename]" if counts(path.encode()) else path
            if number > limit or limit > previous.get(path, {}).get(kind, 0):
                print(f"{label} {kind}: observed={number} listed={limit}")
                failed = True
            elif number < limit:
                print(f"{label} {kind}: observed={number} listed={limit}; lower the budget in {BUDGET}")
    print(" ".join(f"{kind}={totals[kind]}" for kind in sorted({"email", *PATTERNS})))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
