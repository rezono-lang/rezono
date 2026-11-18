"""Warn about newly hardcoded presentation and policy literals in a Git comparison."""

import argparse
from collections import Counter
from pathlib import PurePosixPath
import re
import subprocess


SUFFIXES = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".scss", ".html", ".svg",
            ".yaml", ".yml", ".json", ".dl", ".sql", ".sh", ".go", ".rs"}
PACK_DIRS = {"facts", "labels", "messages", "schema", "rules", "rezono", "calc", "icons"}
PACK_FILES = {"pack.yaml", "channels.yaml", "questions.yaml", "sweeps.yaml", "views.yaml", "key.yaml"}
COLOR = re.compile(r"(?<![\w#])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})(?![\w-])", re.I)
QUOTED = re.compile(r"""(?P<quote>['"\x60])(?P<text>(?:\\.|(?!(?P=quote))[^\\])*)(?P=quote)""")
SCOPE = r"(?:[a-z]\w*_)?(?:zone|role)(?:_name)?"
FIELD = re.compile(rf"""(?<!\w){SCOPE}['"]?\s*\]?\s*(?:!=|==|[:=])\s*$""", re.I)
SCOPE_ARGUMENT = re.compile(r"\b\w*(?:__role|__zone|zone_of)\([^(),]*,\s*")
COMPARE = re.compile(r"\b(\w+)\s*!?=\s*$")
READER = re.compile(r"""(?:\b(?:label|title|reason|message|description|detail|text|aria-label)['"]?\s*[:=]\s*|\b(?:print|alert|\w*Error)\(\s*)[fr]?$""", re.I)
DATA_FIELD = re.compile(rf"""(?:^|[{{,]\s*)\s*(?P<key>{SCOPE}|label|title|reason|message|description|detail)\s*:\s*(?P<value>[^'"{{[|>#\s][^,}}\n#]*)""", re.I)
PROSE = re.compile(r"\b(?:a|an|the|is|are|was|were|has|have|can|cannot|does|must|could|your)\b", re.I)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
MESSAGES = {
    "colour": "A new hex colour could come from a pack palette.",
    "reader": "New reader-facing text could come from a pack message or label.",
    "scope": "A literal zone or role name could come from a pack fact or rule.",
}


def literal(prefix, value, suffix, line):
    binding = False
    if suffix == ".dl" and (compared := COMPARE.search(prefix)):
        arguments = (line[m.end():] for m in SCOPE_ARGUMENT.finditer(line))
        binding = any(re.match(re.escape(compared[1]) + r"\s*\)", arg) for arg in arguments)
    if re.fullmatch(r"[A-Za-z][\w.-]*", value) and (
        FIELD.search(prefix) or binding or (suffix == ".dl" and any(
            m.end() == len(prefix) for m in SCOPE_ARGUMENT.finditer(prefix)
        ))
    ):
        return "scope", value
    # A message slot also admits short/lowercase text. Elsewhere require natural
    # prose, so identifiers, SQL, templates and arbitrary string values stay quiet.
    words = value.split()
    if len(words) >= 2 and not value.startswith("::") and (READER.search(prefix) or (
        len(words) >= 4 and PROSE.search(value) and
        re.fullmatch(r"[\w'’.,:!? ()-]+", value) and not value.isupper() and
        not re.match(r"(?:SELECT|UPDATE|INSERT|DELETE|CREATE|ALTER|WITH|CASE)\b", value, re.I)
    )):
        return "reader", value
    return None


def findings(line, suffix):
    stripped = line.lstrip()
    if stripped.startswith(("//", "/*", "* ", '"""', "'''", "-- ")) or (
        stripped.startswith("#") and suffix not in {".css", ".scss"}
    ):
        return
    for match in COLOR.finditer(line):
        before = line[:match.start()].rstrip()
        if not (before.endswith(("'", '"', ":", ",", "(")) or re.search(r"[\w-]+\s*:[^;{}]*$", before)):
            continue
        yield "colour", match[0].lower()
    for match in QUOTED.finditer(line):
        if item := literal(line[:match.start()], match["text"], suffix, line):
            yield item
    if suffix in {".yaml", ".yml"}:
        for match in DATA_FIELD.finditer(line):
            if item := literal(match["key"] + ": ", match["value"].strip(), suffix, line):
                yield item


def git(*args):
    return subprocess.check_output(["git", *args])


def sources(tree):
    entries = git("ls-tree", "-r", "-z", "--name-only", tree).decode("utf-8", "surrogateescape").split("\0")
    return {PurePosixPath(name).parent for name in entries if PurePosixPath(name).name == "pack.yaml"}


def source_file(path, pack_roots):
    if path.suffix.lower() not in SUFFIXES or "packs" in path.parts:
        return False
    for parent in path.parents:
        if parent in pack_roots:
            relative = path.relative_to(parent)
            data = path.suffix.lower() in {".json", ".yaml", ".yml", ".dl", ".svg"}
            if (data and relative.parts[0] in PACK_DIRS) or relative.as_posix() in PACK_FILES:
                return False
    return True


def changes(base, head):
    fields = iter(git("diff", "--raw", "-z", "--no-abbrev", "--find-renames", base, head, "--").split(b"\0"))
    for record in fields:
        if not record:
            break
        old_mode, new_mode, old_oid, new_oid, status = record[1:].decode().split()
        old_path = PurePosixPath(next(fields).decode("utf-8", "surrogateescape"))
        new_path = PurePosixPath(next(fields).decode("utf-8", "surrogateescape")) if status.startswith("R") else old_path
        if new_mode.startswith("100"):
            yield old_path, new_path, old_oid if old_mode.startswith("100") else None, new_oid


def additions(old_oid, new_oid, suffix):
    if not old_oid:
        blob = git("cat-file", "blob", new_oid)
        if b"\0" not in blob:
            for number, line in enumerate(blob.decode("utf-8", "replace").splitlines(), 1):
                for item in findings(line, suffix):
                    yield number, item
        return
    if old_oid == new_oid:
        return
    diff = git("diff", "--no-ext-diff", "--no-textconv", "--unified=0", old_oid, new_oid, "--")
    removed = Counter()
    added = []
    number = None
    for line in diff.decode("utf-8", "replace").splitlines():
        if match := HUNK.match(line):
            number = int(match[1])
        elif number is not None and line.startswith("-"):
            removed.update(findings(line[1:], suffix))
        elif number is not None and line.startswith("+"):
            added.extend((number, item) for item in findings(line[1:], suffix))
            number += 1
    for number, item in added:
        if removed[item]:
            removed[item] -= 1
        else:
            yield number, item


def annotate(path, number, category):
    # GitHub workflow command properties must not interpret characters in filenames.
    escaped = str(path).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    print(f"::warning file={escaped},line={number},title=Pack literal::{MESSAGES[category]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    base = git("merge-base", args.base, args.head).decode().strip()
    old_roots, new_roots = sources(base), sources(args.head)
    for old_path, new_path, old_oid, new_oid in changes(base, args.head):
        if source_file(new_path, new_roots):
            if old_path.suffix != new_path.suffix or not source_file(old_path, old_roots):
                old_oid = None
            for number, (category, _) in additions(old_oid, new_oid, new_path.suffix.lower()):
                annotate(new_path.as_posix(), number, category)


if __name__ == "__main__":
    main()
