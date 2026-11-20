"""Preflight findings are offer-selection rows: decisions/code-does-not-decide.md.

The expectation is the behaviour of run/read_only_preflight.py under decisions/run-offline-acceptance.md,
"Read-only preflight": distinguish a changed price, insufficient capacity and unavailable reads.
"""
import ast

import pytest

from offline_cases import RUN, implementation

FINDINGS = {"price_changed", "price_unknown", "insufficient_stock", "stock_unknown"}


def literals(name):
    tree = ast.parse((RUN / name).read_text(encoding="utf-8"))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def pack_reads(monkeypatch):
    """The (pack, relation) pairs whose derived rows the code reads."""
    from rezono_compiler import batch

    seen = set()
    read = batch.read

    def spy(con, prog, names=None):
        rows = read(con, prog, names)
        seen.update((prog.pack, name) for name in rows)
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return seen


def constant(value):
    return lambda _sku: value


def test_preflight_findings_come_from_offer_selection(monkeypatch):
    assert not literals("read_only_preflight.py") & FINDINGS, "the findings are written in code, not in the pack"
    seen = pack_reads(monkeypatch)
    inspect = implementation("read_only_preflight.py", "inspect_offer")
    assert set(inspect("sample", 164000, 2, constant(164001), constant(1))["findings"]) == {
        "price_changed", "insufficient_stock"}
    assert set(inspect("sample", 164000, 2, constant(None), constant(2))["findings"]) == {"price_unknown"}
    assert set(inspect("sample", 164000, 2, constant(164000), constant(None))["findings"]) == {"stock_unknown"}
    assert inspect("sample", 164000, 2, constant(164000), constant(2))["findings"] == []
    assert ("offer-selection", "preflight_finding") in seen, sorted(seen)
