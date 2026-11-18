"""Public library checkout and exact-row source companions for operation tests."""

import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import pack as packs
from rezono_compiler import sources, writer
from support import REPO


def origin(name: str) -> dict:
    return {"kind": "person", "name": "register", "position": name}


def companion(d: Path, fname: str = "valid.yaml", of=lambda ref, n: [origin(f"row-{n}")]) -> bytes:
    """Write an exact-row companion for a fact file: `of(ref, n)` gives the sources of its n-th row."""
    p = packs.read(d)
    path = d / "facts" / fname
    refs = [(e["row"]["relation"], e["row"]["key"]) for e in sources.text_entries(p, fname, path.read_text("utf-8"))]
    entries = [{"row": {"relation": t, "key": k}, "sources": of((t, k), n)} for n, (t, k) in enumerate(refs)]
    text = sources.canonical_sidecar(p, path, entries)
    path.with_name(fname.removesuffix(".yaml") + ".sources.yaml").write_bytes(text.encode("utf-8"))
    return text.encode("utf-8")


def per_record(ref, n) -> list[dict]:
    """One origin per record of the file: an inlined element (its id derived from its owner's) shares it."""
    return [origin(f"record-{yaml.safe_load(ref[1])[0].split('/')[0]}")]


@pytest.fixture
def library():
    work = writer.work_dir()
    try:
        d = writer.checkout(REPO / "examples" / "library", work)
        (d / "facts" / "errors.yaml").unlink()
        yield d
    finally:
        shutil.rmtree(work, ignore_errors=True)
