"""What travels with a pack for its imports to resolve (modules.closure): every directory an import names,
each checked against its pin, never through a symbolic link. Small packs of only a pack.yaml suffice: the
pin covers the definition files, and pack.yaml is one."""

import os
from pathlib import Path

import pytest
import yaml

from rezono_compiler import modules


def pack(d: Path, name: str, imports=()) -> Path:
    """A pack of only a pack.yaml; `imports` are (name, path from d) of packs written before."""
    d.mkdir(parents=True)
    pins = [{"name": n, "path": p, "sha256": modules.pack_hash((d / p).resolve())} for n, p in imports]
    (d / "pack.yaml").write_text(yaml.safe_dump({"name": name, "version": "0.1.0", "default_language": "nl",
                                                 "imports": pins}), "utf-8")
    return d


def test_a_pack_reached_by_two_paths_travels_at_both(tmp_path):
    """A diamond: b and c each import their own copy of d. Each importer names its own path, so both go."""
    pack(tmp_path / "d1", "d")
    pack(tmp_path / "d2", "d")
    pack(tmp_path / "b", "b", [("d", "../d1")])
    pack(tmp_path / "c", "c", [("d", "../d2")])
    a = pack(tmp_path / "a", "a", [("b", "../b"), ("c", "../c")])
    base, found = modules.closure(a)
    assert base == tmp_path
    assert sorted(d.name for _, d in found) == ["b", "c", "d1", "d2"]
    copy = modules.copy_closure(a, tmp_path / "copy")
    assert copy == tmp_path / "copy" / "a"
    assert sorted(p.name for p in (tmp_path / "copy").iterdir()) == ["a", "b", "c", "d1", "d2"]
    assert modules.closure(copy)[0] == tmp_path / "copy"  # the copy resolves its imports, pins included


def test_an_import_through_a_symbolic_link_is_refused(tmp_path):
    """A copy cannot keep the link's alias, so the import would not resolve there: refused up front."""
    pack(tmp_path / "b", "b")
    os.symlink(tmp_path / "b", tmp_path / "alias", target_is_directory=True)
    a = pack(tmp_path / "a", "a", [("b", "../alias")])
    with pytest.raises(ValueError, match="symbolic link"):
        modules.closure(a)


def test_an_import_that_is_not_its_pin_is_refused(tmp_path):
    b = pack(tmp_path / "b", "b")
    a = pack(tmp_path / "a", "a", [("b", "../b")])
    (b / "pack.yaml").write_text((b / "pack.yaml").read_text("utf-8") + "# changed\n", "utf-8")
    with pytest.raises(ValueError, match="not the pinned"):
        modules.closure(a)


def test_a_check_runs_before_anything_is_written(tmp_path):
    a = pack(tmp_path / "a", "a")

    def refuse(where):
        raise PermissionError(where)

    with pytest.raises(PermissionError):
        modules.copy_closure(a, tmp_path / "copy", check=refuse)
    assert not (tmp_path / "copy").exists()
