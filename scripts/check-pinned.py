"""Every package in this Python environment runs at the version its lock fixes (docs/ci.md#8-pinned-versions).

  python scripts/check-pinned.py requirements/run.txt

Run in the fresh virtualenv scripts/install-python.sh makes: a package missing from the lock, or at
another version, fails the job, so nothing runs on a version nobody chose.
"""

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWN = re.compile(r"^rezono-")  # this repository's packages, installed from source
TOOLING = {"pip"}  # comes with the pinned Python itself


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main() -> int:
    lock = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "requirements" / "dev.txt"
    pinned = {}
    for line in lock.read_text("utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]*\])?==([^\s;]+)", line)
        if m:
            pinned[norm(m.group(1))] = m.group(3)
    bad = []
    for d in sorted(metadata.distributions(), key=lambda d: norm(d.metadata["Name"])):
        name = norm(d.metadata["Name"])
        if OWN.match(name) or name in TOOLING:
            continue
        if name not in pinned:
            bad.append(f"{name} {d.version}: not in {lock.name}")
        elif pinned[name] != d.version:
            bad.append(f"{name} {d.version}: {lock.name} fixes {pinned[name]}")
    for b in bad:
        print(b, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
