"""Check that NOTICE assigns a licence to every tracked file, using only the standard library."""

from fnmatch import fnmatchcase
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SKIPPED = ("LICENSE", "LICENSES/", "NOTICE")
ENTRY = re.compile(r"^ {2,}- (?P<pattern>\S+)(?: \(except (?P<exception>\S+)\))?$")


def notice_patterns(text):
    """Return (pattern, exception) pairs from the indented entries of NOTICE."""
    return [(match["pattern"], match["exception"])
            for match in map(ENTRY.match, text.splitlines()) if match]


def glob_matches(pattern, path):
    """Match one NOTICE glob: `*` stays within a path segment, `**/` spans any directories."""
    if pattern.startswith("**/"):
        rest = pattern[3:]
        parts = path.split("/")
        return any(glob_matches(rest, "/".join(parts[index:])) for index in range(len(parts)))
    pattern_parts, path_parts = pattern.split("/"), path.split("/")
    if "**" in pattern_parts:
        cut = pattern_parts.index("**")
        head, tail = "/".join(pattern_parts[:cut]), "/".join(pattern_parts[cut:])
        prefix = path_parts[:cut]
        return (len(path_parts) > cut and glob_matches(head, "/".join(prefix))
                and glob_matches(tail, "/".join(path_parts[cut:])))
    return len(pattern_parts) == len(path_parts) and all(
        fnmatchcase(name, part) for part, name in zip(pattern_parts, path_parts))


def covered(pattern, exception, path):
    if exception and glob_matches(exception if "/" in exception else "**/" + exception, path):
        return False
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return glob_matches(pattern, path)


def uncovered(paths, patterns):
    return [path for path in paths
            if not any(path == skip or (skip.endswith("/") and path.startswith(skip)) for skip in SKIPPED)
            and not any(covered(pattern, exception, path) for pattern, exception in patterns)]


def tracked_files(root):
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return [path for path in output.decode("utf-8").split("\0") if path]


class Notice(unittest.TestCase):
    def test_every_tracked_file_has_a_licence_in_notice(self):
        patterns = notice_patterns((ROOT / "NOTICE").read_text(encoding="utf-8"))
        self.assertTrue(patterns, "NOTICE lists no path patterns")
        missing = uncovered(tracked_files(ROOT), patterns)
        if missing:
            self.fail("files outside every NOTICE pattern:\n" + "\n".join(missing))

    def test_a_file_outside_every_pattern_is_reported(self):
        patterns = notice_patterns(
            "- Apache-2.0:\n  - scripts/\n  - contracts/*.py\n  - examples/**/*.py\n"
            "- CC-BY-4.0:\n  - examples/ (except *.py)\n  - **/README.md\n")
        paths = ["LICENSE", "LICENSES/CC0-1.0.txt", "NOTICE", "README.md", "scripts/a.py",
                 "contracts/check.py", "contracts/python/x.py", "examples/a/b.py", "examples/a/b.yaml",
                 "deep/dir/README.md", "stray.txt"]
        self.assertEqual(uncovered(paths, patterns), ["contracts/python/x.py", "stray.txt"])


if __name__ == "__main__":
    sys.exit(unittest.main())
