"""Central read-access declarations: packs/std-access declares may_read_full(role, kind) and its importing
packs state their full-read grants explicitly (decisions/central-read-access.md, section 1)."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import modules, pack
from rezono_compiler import rules as ir
from support import FIXTURE

REPO = Path(__file__).resolve().parents[2]
STD_ACCESS = REPO / "packs" / "std-access"
CONSUMERS = (
    "examples/subsidy",
    "examples/platform",
    "run/packs/probe-profiles",
    "tests/fixtures/neutral",
)
# Consumers that grant full-kind read access (platform uses element-scoped grants by default).
FULL_CONSUMERS = (
    "examples/subsidy",
    "run/packs/probe-profiles",
    "tests/fixtures/neutral",
)


class MissingExplicitMayReadFull(AssertionError):
    """packs/std-access or one of its importing packs does not yet declare or use may_read_full(role, kind)."""


def _std_access_program(tmp_path: Path):
    probe = Path(shutil.copytree(FIXTURE, tmp_path / "std-access-probe"))
    meta_path = probe / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["imports"] = [{"name": "std-access", "path": str(STD_ACCESS), "sha256": modules.pack_hash(STD_ACCESS)}]
    meta_path.write_text(yaml.safe_dump(meta), encoding="utf-8")
    return ir.load(pack.read(probe).rules)


def test_std_access_and_consumers_declare_may_read_full(tmp_path):
    prog = _std_access_program(tmp_path)
    assert prog.rules == {}, "std-access itself must declare no grant clauses"
    declared = {name: rel for name, rel in prog.relations.items() if rel.role != "base"}
    assert declared, "packs/std-access declares no rule relations"
    if "may_read_full" not in declared:
        raise MissingExplicitMayReadFull("packs/std-access does not declare may_read_full(role, kind)")
    rel = declared["may_read_full"]
    assert rel.extend is True and rel.closes is None and rel.explain != "fold"  # @extend, no @closes, no @fold
    assert [(col.name, col.type) for col in rel.key] == [("role", "string"), ("kind", "string")]
    assert "may_read_full" in pack.ACCESS

    for rel in CONSUMERS:
        model = pack.read(REPO / rel)
        prog = ir.load(model.rules)
        if "may_read_full" not in prog.relations:
            raise MissingExplicitMayReadFull(f"{rel} does not include may_read_full in its compiled rules")
        if rel in FULL_CONSUMERS and not prog.rules_for("may_read_full"):
            raise MissingExplicitMayReadFull(f"{rel} has no may_read_full grant clauses")
