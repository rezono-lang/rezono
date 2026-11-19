"""Compare tracked file contents and names with the per-file disclosure budget.

In a pull request or merge-group run it also refuses commit messages, and the pull request
title and body, that contain a Co-authored-by trailer or an address other than the author's.
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
CO_AUTHOR = re.compile(rb"^[ \t]*co-authored-by[ \t]*:", re.I | re.M)
# The sign-off GitHub's dependency bot writes; assembled so this file holds no address itself.
BOT_SIGN_OFF = b"Signed-off-by: dependabot[bot] <support" + b"@github.com>"
PATTERNS = {
    "machine_path": re.compile(rb"(?:[A-Z]:[/\\]+(?:Users|Documents and Settings)[/\\]+|/(?:Users|home)/|/mnt/[a-z]/Users/)[\w.-]+", re.I),
    "ticket": re.compile(rb"RV-[A-Z]*[0-9]+"),
    "old_name": re.compile(rb"(?<![A-Za-z0-9])(?:re[d]e\.dev|re[d]e|rec[k]on|a[t]las)(?![A-Za-z0-9])", re.I),
}


def foreign(address):
    return address != AUTHOR and not BOT.fullmatch(address) and not EXAMPLE.fullmatch(address.split(b"@")[-1].lower())


def counts(data):
    found = {name: sum(1 for _ in pattern.finditer(data)) for name, pattern in PATTERNS.items()}
    found["email"] = sum(foreign(m.group()) for m in EMAIL.finditer(data))
    return {kind: number for kind, number in sorted(found.items()) if number}


def message_counts(data):
    """Count Co-authored-by trailers and foreign addresses in a commit message or PR text."""
    lines = (line for line in data.splitlines() if line.strip() != BOT_SIGN_OFF)
    found = {
        "co_author": len(CO_AUTHOR.findall(data)),
        "email": sum(foreign(m.group()) for line in lines for m in EMAIL.finditer(line)),
    }
    return {kind: number for kind, number in found.items() if number}


def event_texts():
    """Yield (label, text) for each commit message and PR text of this pull request or merge group."""
    name, path = os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_EVENT_PATH")
    if name not in ("pull_request", "merge_group") or not path:
        return
    event = json.loads(Path(path).read_bytes())
    if name == "pull_request":
        pull = event["pull_request"]
        base, head = pull["base"]["sha"], pull["head"]["sha"]
        yield "pull request title", (pull.get("title") or "").encode()
        yield "pull request body", (pull.get("body") or "").encode()
    else:
        group = event["merge_group"]
        base, head = group["base_sha"], group["head_sha"]
        yield "merge group message", ((group.get("head_commit") or {}).get("message") or "").encode()
    log = subprocess.check_output(["git", "log", "-z", "--format=%h%n%B", f"{base}..{head}"])
    for entry in filter(None, log.split(b"\0")):
        commit, _, message = entry.partition(b"\n")
        yield f"commit {commit.decode()} message", message


def check_messages():
    failed = False
    for label, text in event_texts():
        for kind, number in sorted(message_counts(text).items()):
            # Print counts only, never the trailer or the address itself.
            print(f"{label} {kind}: observed={number} allowed=0")
            failed = True
    return failed


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
    args = parser.parse_args()
    actual = scan()
    budget = read_budget(Path(BUDGET).read_bytes())
    previous = budget
    if args.base:
        tree = subprocess.check_output(["git", "ls-tree", args.base, "--", BUDGET])
        if tree:
            previous = read_budget(subprocess.check_output(["git", "show", f"{args.base}:{BUDGET}"]))
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
    failed = check_messages() or failed
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
