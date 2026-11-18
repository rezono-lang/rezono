"""The golden form of a pack's compiled output: every file as the compiler writes it, except a file
above LARGE bytes, which becomes a line in large-files.json (path, sha256, bytes). The tests compare
this form; every regenerated large file would otherwise stay in the history for good. CI uploads the
full output too when it differs (artifact compiled-full). A file named in FULL is kept in full at any
size: other tools read it back from the golden, and a hash cannot be read.

Usage: python compiler/tests/golden.py <pack> <out>   (writes the golden form of <pack> to <out>)
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

LARGE = 1_000_000
MANIFEST = "large-files.json"
# Compiler output names (not pack names) kept in full at any size: the viewer, the contract checks
# and the documentation scripts read the schema bundle back from the golden, and a hash cannot be read.
FULL = frozenset({"bundle/schema-bundle.json"})


def golden(files: dict[str, str]) -> dict[str, bytes]:
    out, large = {}, []
    for path, text in sorted(files.items()):
        data = text.encode("utf-8")
        if len(data) > LARGE and path not in FULL:
            large.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": str(len(data))})
        else:
            out[path] = data
    if large:
        out[MANIFEST] = (json.dumps(large, indent=1, sort_keys=True) + "\n").encode("utf-8")
    return out


def differences(got: dict[str, bytes], want: dict[str, bytes], context: int = 3) -> str:
    """What differs between two trees of files, in time linear in their size: each file missing, extra or changed, and
    for a changed one its first differing line with `context` lines from there. Empty when the trees are equal.

    A test asserts `not differences(got, want)`, never `got == want`: on CI pytest explains a failed `==` of two dicts
    with `difflib.ndiff` over their whole pretty-printed form, without a bound, and that is quadratic in their size. Six
    stale goldens kept the nightly `examples` shard in those diffs for two hours (run 43682535960, 15-11-2026). CI
    uploads the whole compiled output of a failed golden (artifact compiled-full)."""
    out = [f"missing: {p}" for p in sorted(want.keys() - got.keys())]
    out += [f"extra: {p}" for p in sorted(got.keys() - want.keys())]
    for p in sorted(want.keys() & got.keys()):
        if got[p] != want[p]:
            a, b = want[p].splitlines(), got[p].splitlines()
            i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            out.append(f"changed: {p}, {len(a)} lines expected and {len(b)} got, first at line {i + 1}:")
            out += [f"  - {x[:200]!r}" for x in a[i:i + context]] + [f"  + {y[:200]!r}" for y in b[i:i + context]]
    return "\n".join(out)


def main(pack_dir: str, out_dir: str) -> None:
    from rezono_compiler import emit, pack

    for path, data in golden(emit.compile_pack(pack.read(pack_dir))).items():
        target = Path(out_dir) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


if __name__ == "__main__":
    main(*sys.argv[1:3])
