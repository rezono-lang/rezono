"""Compare tracked file contents and names with the per-file disclosure budget."""

import argparse
import json
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
    "old_name": re.compile(rb"(?<![A-Za-z0-9])(?:re[d]e\.dev|re[d]e|rec[k]on)(?![A-Za-z0-9])", re.I),
}


def counts(data):
    found = {name: sum(1 for _ in pattern.finditer(data)) for name, pattern in PATTERNS.items()}
    emails = (m.group() for m in EMAIL.finditer(data))
    found["email"] = sum(
        address != AUTHOR and not BOT.fullmatch(address) and not EXAMPLE.fullmatch(address.split(b"@")[-1].lower())
        for address in emails
    )
    return {kind: number for kind, number in sorted(found.items()) if number}


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    args = parser.parse_args()
    actual = scan()
    budget = json.loads(Path(BUDGET).read_bytes())
    previous = budget
    if args.base:
        tree = subprocess.check_output(["git", "ls-tree", args.base, "--", BUDGET])
        if tree:
            previous = json.loads(subprocess.check_output(["git", "show", f"{args.base}:{BUDGET}"]))
    failed = False
    totals = Counter()
    for path in sorted(set(actual) | set(budget)):
        observed, allowed = actual.get(path, {}), budget.get(path, {})
        totals.update(observed)
        for kind in sorted(set(observed) | set(allowed)):
            number, limit = observed.get(kind, 0), allowed.get(kind, 0)
            if number != limit or limit > previous.get(path, {}).get(kind, 0):
                # Print counts only, including when a filename itself contains a finding.
                label = "[redacted filename]" if counts(path.encode()) else path
                print(f"{label} {kind}: observed={number} listed={limit}")
                failed = True
    print(" ".join(f"{kind}={totals[kind]}" for kind in sorted({"email", *PATTERNS})))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
