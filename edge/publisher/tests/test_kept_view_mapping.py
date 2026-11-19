"""The mapping boundary of kept replay, from decisions/kept-view-mapping.md.

The archive of the subsidy example carries its theory mapping (`views.yaml` at the main pack root). The current
verifier admits a mapping that it can read and type against the archive's own pinned closure, before any archived
code is installed. It refuses a malformed or ill-typed mapping there, naming the file.
"""

import io
import tarfile
from pathlib import Path

import pytest
from rezono_publisher import kept

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples" / "subsidy"


def unpacked(tmp_path):
    """The pack/ part of the example's archive, as replay unpacks it."""
    with tarfile.open(fileobj=io.BytesIO(kept.archive(ROOT, EXAMPLE)), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.name.startswith("pack/")]
        tar.extractall(tmp_path, members=members, filter="data")
    root = tmp_path / "pack"
    (main,) = [p.parent for p in root.rglob("views.yaml") if (p.parent / "facts").is_dir()]
    return root, main


def test_a_typed_theory_mapping_is_admitted_before_install(tmp_path):
    root, main = unpacked(tmp_path / "typed")
    assert kept.archived_pack(root) == (main.resolve(), [])

    # Malformed: refused at the boundary, naming the file.
    root, main = unpacked(tmp_path / "malformed")
    (main / "views.yaml").write_text("not even parsed: [", encoding="utf-8")
    found, errors = kept.archived_pack(root)
    assert found is None and errors and all("views.yaml" in e for e in errors), errors

    # Ill-typed: a source kind the domain does not have.
    root, main = unpacked(tmp_path / "ill-typed")
    text = (main / "views.yaml").read_text(encoding="utf-8")
    assert "populated_from: scheme_parameter" in text
    (main / "views.yaml").write_text(text.replace("populated_from: scheme_parameter",
                                                  "populated_from: no_such_kind", 1), encoding="utf-8")
    found, errors = kept.archived_pack(root)
    assert found is None and errors and all("views.yaml" in e for e in errors), errors
