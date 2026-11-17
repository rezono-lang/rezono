"""A copy of a pack with its facts multiplied, for the scaling check of the profile (docs/gui.md, O(page)).

  python deploy/profiles/edge/multiply.py PACK_DIR K [--keep KIND ...]

Writes the copy beside the pack, as `<dir>-x<K>` (so its relative imports still hold), named `<name>-x<K>`,
and prints its directory. Copy 0 keeps every id; copy c (1 <= c < K) is every record again with every value
that is the id of a record of the pack's facts renamed, so each copy is the same graph, disjoint from the
others. A new id keeps the old one's shape, so a pack's id pattern still holds: its trailing hex digits (at
least 4) become as many of sha256(id, c), else `-x<c>` is appended. Every new id is unique: a hex name that is
taken (few digits, many copies) is drawn again, and when 16 draws are taken `-x<c>` is appended instead.
Records of a kept kind (for example roles the deployment names) are not copied.
Text that is not an id stays as it is. No domain knowledge: only the facts' own ids. Used by the profile's
scaling check (profile.sh) and by the scale ladder (probes/scale, RV-Z06).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

import yaml

SKIP = ("expected", "golden", "test_*.py")
HEX = re.compile(r"[0-9a-f]{4,}$")


def renamed(id_: str, c: int, draw: int = 0) -> str:
    m = HEX.search(id_)
    if not m:
        return f"{id_}-x{c}"
    digits = hashlib.sha256((f"{id_}\0{c}" + (f"\0{draw}" if draw else "")).encode()).hexdigest()
    while len(digits) < len(m.group()):
        digits += hashlib.sha256(digits.encode()).hexdigest()
    return id_[:m.start()] + digits[:len(m.group())]


def multiply(pack: Path, k: int, keep: set[str]) -> Path:
    out = pack.with_name(f"{pack.name}-x{k}")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(pack, out, ignore=shutil.ignore_patterns(*SKIP))
    meta = yaml.safe_load((out / "pack.yaml").read_text(encoding="utf-8"))
    meta["name"] = f"{meta['name']}-x{k}"
    (out / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    files = sorted((out / "facts").glob("*.yaml"))
    docs = {f: yaml.safe_load(f.read_text(encoding="utf-8")) or {} for f in files}
    ids, taken = set(), set()  # the ids of copied records; every id
    for d in docs.values():
        for kind, rs in d.items():
            got = {r["id"] for r in rs or [] if isinstance(r, dict) and isinstance(r.get("id"), str)}
            taken |= got
            if kind not in keep:
                ids |= got
    names: dict[tuple[str, int], str] = {}  # the hex names given, so every reference reads the same one

    def name(id_, c):
        if not HEX.search(id_):
            return renamed(id_, c)
        if (id_, c) not in names:
            new = next((n for n in (renamed(id_, c, draw) for draw in range(16)) if n not in taken), f"{id_}-x{c}")
            if new in taken:
                raise ValueError(f"no free name for copy {c} of {id_}")
            taken.add(new)
            names[id_, c] = new
        return names[id_, c]

    def rename(v, c):
        if isinstance(v, str):
            return name(v, c) if v in ids else v
        if isinstance(v, list):
            return [rename(x, c) for x in v]
        if isinstance(v, dict):
            return {key: rename(x, c) for key, x in v.items()}
        return v

    for f, d in docs.items():
        grown = {kind: (rs if kind in keep else list(rs or []) + [rename(r, c) for c in range(1, k) for r in rs or []])
                 for kind, rs in d.items()}
        f.write_text(yaml.safe_dump(grown, sort_keys=False, allow_unicode=True, width=10_000), encoding="utf-8")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="multiply.py")
    p.add_argument("pack", type=Path)
    p.add_argument("k", type=int)
    p.add_argument("--keep", nargs="*", default=[], help="kinds whose records are not copied")
    a = p.parse_args(argv)
    if a.k < 2:
        p.error("K is 2 or more")
    print(multiply(a.pack.resolve(), a.k, set(a.keep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
