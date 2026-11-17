"""rezono-checker --proof P --manifest M --rules R [--role ROLE] [--snapshot-root DIR]

Prints the JSON report. Exit 0 if the proof is valid, 1 if not, 2 on unreadable input.
"""

import argparse
import sys
from pathlib import Path

import yaml

from .check import check, render
from .rules import load_rules
from .snapshots import resolve


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rezono-checker", description="Check a Rezono proof against a manifest.")
    ap.add_argument("--proof", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--rules", required=True, type=Path)
    ap.add_argument("--role", help="Filter the report for this role. The checks always use the complete snapshots.")
    ap.add_argument("--snapshot-root", type=Path, help="Base for relative snapshot URIs (default: the manifest's folder).")
    args = ap.parse_args(argv)
    try:
        proof, manifest, rules_doc = (yaml.safe_load(p.read_text()) for p in (args.proof, args.manifest, args.rules))
        root = args.snapshot_root or args.manifest.parent
        report = check(proof, manifest, load_rules(rules_doc), lambda uri: resolve(uri, root).read_bytes(), args.role)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as e:
        print(f"rezono-checker: unreadable input: {e!r}", file=sys.stderr)
        return 2
    sys.stdout.write(render(report))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
