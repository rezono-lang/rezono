"""Renewal blocks come from the provider terms pack: decisions/code-does-not-decide.md.

The expectation is the behaviour of run/ovh_renewal.py under decisions/run-price-enforcement.md, "Conditions for
the OVHcloud guarantee": the bound covers the whole run.
"""
import ast

import pytest

from offline_cases import RUN, implementation

DEADLINE = "2032-05-04T22:00:00Z"
CODES = {"renews_automatically", "renewal_forced", "not_deleted_at_expiration", "renewal_unknown",
         "expiration_unknown", "period_ends_before_deadline", "engagement_unknown", "engaged_beyond_expiration"}


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


def service(**changes):
    renew = {"automatic": False, "forced": False, "deleteAtExpiration": True, "manualPayment": False, "period": 1}
    body = {"serviceId": 9, "domain": "srv-1.example.org", "status": "ok", "creation": "2032-05-04",
            "expiration": "2032-06-03", "engagedUpTo": None, "renewalType": "manual", "renew": renew}
    for key, value in changes.items():
        if key in renew:
            renew[key] = value
        else:
            body[key] = value
    return body


def test_renewal_blocks_come_from_provider_terms(monkeypatch):
    assert (RUN / "packs" / "provider-terms" / "pack.yaml").is_file(), "run/packs/provider-terms is missing"
    assert not literals("ovh_renewal.py") & CODES, "the blocking codes are written in code, not in the pack"
    seen = pack_reads(monkeypatch)
    blocks = implementation("ovh_renewal.py", "blocks")

    assert blocks(service(), DEADLINE) == []
    assert blocks(service(engagedUpTo="2032-06-03"), DEADLINE) == []
    assert blocks(service(automatic=True), DEADLINE) == ["renews_automatically"]
    assert blocks(service(forced=True), DEADLINE) == ["renewal_forced"]
    assert blocks(service(automatic=True, deleteAtExpiration=False), DEADLINE) == [
        "not_deleted_at_expiration", "renews_automatically"]
    assert blocks(service(engagedUpTo="2032-07-03"), DEADLINE) == ["engaged_beyond_expiration"]
    assert blocks(service(), "2032-06-02T23:59:59Z") == []
    assert blocks(service(), "2032-06-03T01:00:00+01:00") == ["period_ends_before_deadline"]
    assert blocks(service(expiration=None), DEADLINE) == ["expiration_unknown"]
    assert blocks(service(deleteAtExpiration="true"), DEADLINE) == ["renewal_unknown"]
    assert blocks({k: v for k, v in service().items() if k != "engagedUpTo"}, DEADLINE) == ["engagement_unknown"]
    assert ("provider-terms", "renewal_block") in seen, sorted(seen)
