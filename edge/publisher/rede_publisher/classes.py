"""Where a pack may be published (SO-5, Arbiter (4), 11-11-2026): a pack says what its data is, a profile says
what it carries, and a pack whose class the profile does not carry is refused before anything is written.

- The pack's class is the key `class` of its pack.yaml (contracts/pack.yaml), given by whoever owns the data.
  A pack without it is `unclassified`, and that is said, not assumed: a profile carries it only if it lists it.
- The profile's list is `publish.classes`: a statement about the place, made by whoever runs it. A profile
  without the list carries nothing (fails closed).
- This module knows no class by name but `unclassified`, the name of having none. A misspelt class, in either
  file, is in nobody's list.

One function, two callers: the publisher (rede_publisher.__main__) before it computes or writes, and the check
over every profile and the packs it lists, per pull request (`python -m rede_publisher.classes PROFILE...`,
run by tests/test_classes.py over deploy/profiles/*.yaml).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

UNCLASSIFIED = "unclassified"


def pack_class(pack_dir: str | Path) -> str:
    """The class pack.yaml declares, or `unclassified`."""
    meta = yaml.safe_load((Path(pack_dir) / "pack.yaml").read_text(encoding="utf-8")) or {}
    value = meta.get("class", UNCLASSIFIED)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{pack_dir}/pack.yaml: class must be a name, not {value!r}")
    return value


def carried(profile: dict) -> frozenset[str]:
    """The classes a profile publishes: its list `publish.classes`, empty when it has none."""
    listed = ((profile or {}).get("publish") or {}).get("classes") or []
    if not isinstance(listed, list) or not all(isinstance(c, str) and c for c in listed):
        raise ValueError(f"publish.classes must be a list of class names, not {listed!r}")
    return frozenset(listed)


def refusal(pack_dir: str | Path, profile: dict, profile_name: str) -> str | None:
    """Why the profile may not publish the pack, naming both; None when it may."""
    cls = pack_class(pack_dir)
    allowed = carried(profile)
    if cls in allowed:
        return None
    listed = ", ".join(sorted(allowed)) or "nothing (it has no publish.classes)"
    return (f"pack {pack_dir} is class {cls!r} (its pack.yaml; no class there means {UNCLASSIFIED!r}), "
            f"and profile {profile_name} carries {listed} (its publish.classes)")


def profile_packs(profile: dict) -> list[str]:
    """Every pack directory a profile lists: the packs it publishes and the packs its live engine holds."""
    p = profile or {}
    return sorted(set(((p.get("publish") or {}).get("packs") or []) + ((p.get("live") or {}).get("packs") or [])))


def check(profile_path: str | Path, root: str | Path = ".") -> list[str]:
    """Every refusal for the packs a profile lists, paths relative to the repository root."""
    path = Path(profile_path)
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for pack in profile_packs(profile):
        reason = refusal(Path(root) / pack, profile, path.name)
        if reason:
            out.append(reason)
    return out


def main(argv: list[str] | None = None) -> int:
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print("usage: python -m rede_publisher.classes PROFILE...", file=sys.stderr)
        return 1
    refused = [r for p in paths for r in check(p)]
    for r in refused:
        print(f"refused: {r}", file=sys.stderr)
    return 2 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
