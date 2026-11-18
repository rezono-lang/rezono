"""Collect or run cluster-marked pytest items in each repository component."""

import argparse
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys

from pytest import ExitCode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.components import discover_components, pytest_folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    command = [sys.executable, "-m", "pytest", "-q", "--strict-markers",
               "--rezono-cluster", "-m", "cluster", "--rootdir", str(root)]
    if args.collect_only:
        command.append("--collect-only")

    selected = False
    for component in discover_components(root):
        if component.kind not in {"python", "contracts"}:
            continue
        folder = pytest_folder(asdict(component))
        print(f"Checking cluster tests in {folder}", flush=True)
        result = subprocess.run([*command, "--", folder], cwd=root)
        if result.returncode == ExitCode.NO_TESTS_COLLECTED:
            continue
        if result.returncode:
            return result.returncode
        selected = True

    if not selected:
        print("No cluster tests selected in any component.", file=sys.stderr)
        return ExitCode.NO_TESTS_COLLECTED
    return ExitCode.OK


if __name__ == "__main__":
    raise SystemExit(main())
