"""The meaning of a vendor's order status is a pack fact: decisions/code-does-not-decide.md, section 3.

The expectation is the behaviour of run/ovh_order_status.py under decisions/run-price-enforcement.md,
"Correlation". Any other status is unresolved: unknown is explicit.
"""
import ast
import json

import pytest

from offline_cases import RUN, implementation

MEANINGS = {"notPaid": "not_committed", "checking": "pending", "documentsRequested": "pending",
            "delivering": "pending", "delivered": "delivered", "cancelled": "refused"}


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


def test_order_status_meaning_comes_from_provider_terms(monkeypatch):
    assert (RUN / "packs" / "provider-terms" / "pack.yaml").is_file(), "run/packs/provider-terms is missing"
    assert not literals("ovh_order_status.py") & set(MEANINGS), "the vendor's status words are code, not pack facts"
    seen = pack_reads(monkeypatch)
    outcome = implementation("ovh_order_status.py", "outcome")
    expected = {json.dumps(status).encode(): meaning for status, meaning in MEANINGS.items()}
    expected.update({b'"cancelling"': "unresolved", b'"Delivered"': "unresolved", b'"paid"': "unresolved",
                     b"null": "unresolved", b'["delivered"]': "unresolved", b"": "unresolved"})
    assert {body: outcome(body) for body in expected} == expected
    assert ("provider-terms", "order_outcome") in seen, sorted(seen)
