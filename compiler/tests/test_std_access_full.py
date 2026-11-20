"""Central read-access declarations: packs/std-access declares may_read_full(role, kind) and its importing
packs state their full-read grants explicitly (decisions/central-read-access.md, section 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rezono_compiler import modules, pack, rezono_relational
from rezono_compiler import rules as ir
from rezono_compiler.rules_dl import parse_file

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


def _std_access_statements() -> list:
    meta, errors = pack.read_meta(STD_ACCESS), []
    mods, _ = modules.load(STD_ACCESS, meta, errors)
    assert not errors, errors
    texts = [p.read_text(encoding="utf-8") for p in sorted((STD_ACCESS / "rules").glob("*.dl"))]
    texts += [item.text for item in rezono_relational.sources(mods) if item.pack == meta["name"]]
    assert texts, "packs/std-access has no rule source"
    return [stmt for i, text in enumerate(texts) for stmt in parse_file(text, f"std-access:{i}")]


def test_std_access_and_consumers_declare_may_read_full():
    statements = _std_access_statements()
    assert all(stmt[0] == "decl" for stmt in statements), "std-access itself must declare no grant clauses"
    by_name = {stmt[1]: stmt for stmt in statements}
    if "may_read_full" not in by_name:
        raise MissingExplicitMayReadFull("packs/std-access does not declare may_read_full(role, kind)")
    decl = by_name["may_read_full"]
    assert decl[8] is True and decl[9] is None and decl[10] is False  # @extend, no @closes, no @fold
    assert decl[2] == [("role", "string"), ("kind", "string")]
    assert "may_read_full" in pack.ACCESS

    for rel in CONSUMERS:
        model = pack.read(REPO / rel)
        prog = ir.load(model.rules)
        if "may_read_full" not in prog.relations:
            raise MissingExplicitMayReadFull(f"{rel} does not include may_read_full in its compiled rules")
        if rel in FULL_CONSUMERS and not prog.rules_for("may_read_full"):
            raise MissingExplicitMayReadFull(f"{rel} has no may_read_full grant clauses")
