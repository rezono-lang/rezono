#!/usr/bin/env python3
"""Reuse a cached virtualenv's locked distributions, verified file by file (docs/ci.md#8-pinned-versions).

  python -I -S scripts/venv-reuse.py CACHED FRESH LOCK

CACHED is a virtualenv restored from CI's cache, FRESH a virtualenv just made by `python -m venv` from the
pinned runtime, LOCK the lock it must follow. scripts/install-python.sh calls this; on any failure it throws
FRESH away and installs everything as before.

Only distributions the lock pins at exactly their installed version move, never this repository's own
(rede-*, installed from source again) or pip (FRESH has its own). For each, every file its dist-info RECORD
lists must exist inside CACHED as a regular file with the recorded size and SHA-256; only RECORD itself (and
its signature files) may go without a hash. A compiled `__pycache__/*.pyc` that RECORD lists without a hash (the
wheel format allows it; SPARQLWrapper 2.0.0 does it) is not moved: Python compiles it again from the source,
which is checked. A script in bin/ must start with FRESH's own interpreter. All of
it is checked before anything moves; then the listed files move into FRESH, and nothing else does: a file no
RECORD lists, such as a planted .pth, stays behind and is deleted with CACHED. Distributions the lock pins
but CACHED lacks are left to pip, which installs them hash-checked from the lock. Standard library only.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import os
import re
import sys
from pathlib import Path

OWN = re.compile(r"^rede-")
TOOLING = {"pip"}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned(lock: Path) -> dict[str, str]:
    out = {}
    for line in lock.read_text("utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)(\[[^\]]*\])?==([^\s;]+)", line)
        if m:
            out[norm(m.group(1))] = m.group(3)
    return out


def site_packages(venv: Path) -> Path:
    (sp,) = sorted(venv.glob("lib/python*/site-packages"))
    return sp


def metadata(dist_info: Path) -> tuple[str, str]:
    name = version = ""
    for line in (dist_info / "METADATA").read_text("utf-8", errors="replace").splitlines():
        if not line:
            break
        key, _, value = line.partition(":")
        if key == "Name":
            name = value.strip()
        elif key == "Version":
            version = value.strip()
    return norm(name), version


class Refused(Exception):
    pass


def verify(dist_info: Path, cached: Path, fresh: Path) -> list[Path]:
    """The files of one distribution, relative to CACHED, each checked against RECORD."""
    sp = dist_info.parent
    files = []
    with open(dist_info / "RECORD", newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            rel, digest, size = (row + ["", ""])[:3]
            path = Path(os.path.normpath(sp / rel))
            if os.path.isabs(rel) or not path.is_relative_to(cached):
                raise Refused(f"{dist_info.name}: {rel} lies outside the virtualenv")
            if path.is_symlink() or not path.is_file():
                raise Refused(f"{dist_info.name}: {rel} is missing or not a regular file")
            if not digest:
                if path.parent == dist_info and path.name in ("RECORD", "RECORD.jws", "RECORD.p7s"):
                    files.append(path.relative_to(cached))
                    continue
                if path.parent.name == "__pycache__" and path.suffix == ".pyc":
                    continue  # unproven bytecode stays behind; Python compiles it again from the checked source
                raise Refused(f"{dist_info.name}: {rel} has no hash")
            algorithm, _, expected = digest.partition("=")
            if algorithm != "sha256":
                raise Refused(f"{dist_info.name}: {rel} has a {algorithm} hash, not sha256")
            data = path.read_bytes()
            got = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            if got != expected or (size and int(size) != len(data)):
                raise Refused(f"{dist_info.name}: {rel} differs from its RECORD")
            relative = path.relative_to(cached)
            if relative.parts[0] == "bin" and data.startswith(b"#!"):
                interpreter = data.split(b"\n", 1)[0][2:].decode(errors="replace")
                if not re.fullmatch(re.escape(str(fresh / "bin" / "python")) + r"[0-9.]*", interpreter):
                    raise Refused(f"{dist_info.name}: {rel} runs {interpreter}, not this virtualenv's Python")
            if (fresh / relative).exists():
                raise Refused(f"{dist_info.name}: {rel} is already in the fresh virtualenv")
            files.append(relative)
    return files


def main(argv: list[str]) -> int:
    cached, fresh, lock = Path(argv[0]).resolve(), Path(argv[1]).resolve(), Path(argv[2])
    pins = pinned(lock)
    sp = site_packages(cached)
    if sp.relative_to(cached) != site_packages(fresh).relative_to(fresh):
        raise Refused(f"{sp} is for another Python than {fresh}")
    moves, reused, skipped = [], 0, 0
    for dist_info in sorted(sp.glob("*.dist-info")):
        name, version = metadata(dist_info)
        if OWN.match(name) or name in TOOLING or pins.get(name) != version:
            skipped += 1
            continue
        moves += verify(dist_info, cached, fresh)
        reused += 1
    for relative in moves:
        (fresh / relative).parent.mkdir(parents=True, exist_ok=True)
        os.replace(cached / relative, fresh / relative)
    print(f"venv-reuse: {reused} locked distributions, {len(moves)} files verified and reused; "
          f"{skipped} left out (own, pip or not pinned at that version)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (Refused, OSError, ValueError, UnicodeDecodeError) as e:
        print(f"venv-reuse: refused: {e}", file=sys.stderr)
        sys.exit(1)
