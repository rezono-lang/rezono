"""Compare both directions of a complete read of the managed router scope."""

import hashlib

import pytest

from case_support import verified


def records():
    scope = {"run": "active", "router": "boundary", "table": "managed"}
    def rule(identifier, port, **values):
        return {"id": identifier, "source": "192.0.2.0/28", "destination": "198.51.100.7",
                "protocol": "TCP", "first_port": port, "last_port": port, **scope, **values}
    return {
        "router_desired": [rule("stay", 443), rule("needed", 8443)],
        "router_seen": [rule("other-handle", 443), rule("unused", 9443),
                        rule("outside", 8443, table="local"), rule("other-run", 8443, run="prior")],
        "router_sweep": [{"id": "this-read", "complete": True, **scope},
                         {"id": "wrong-table", **(scope | {"table": "local"}), "complete": True}],
        "router_management": [{"id": "active-policy", **scope}],
    }


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: Derive both directions of managed router drift from scoped snapshots in schema/management_firewall.yaml "
    "and rules/management_firewall.dl, consuming the observed-first comparison in std-loop. "
    "Requires native Boolean rule input for sweep completeness and an observed-first std-loop comparison. "
    "The current std-loop drift requires a desired token. Read decisions/platform-management-firewall.md. "
    "Blocked: the test records carry sweep completeness as a Python bool, which no text or integer rule column accepts, so this waits for test_native_boolean_rule_inputs (still red)."))
def test_management_firewall_bidirectional():
    from management_probes import compiled

    data = records()
    for complete in (True, False):
        data["router_sweep"][0]["complete"] = complete
        model, state = compiled(data)
        findings = {("missing", "needed", "this-read"), ("extra", "unused", "this-read")} if complete else set()
        assert state.derived.get("managed_router_drift") == findings
        assert state.derived.get("managed_router_unknown") == (set() if complete else {("active", "boundary", "managed")})
        for row in findings:
            leaves = verified("managed_router_drift", row, state=(model, state))
            assert any(rel.startswith("router_sweep__") and key[0] == "this-read" for rel, key in leaves)
            assert any(rel.startswith("router_management__") and key[0] == "active-policy" for rel, key in leaves)
            assert any(rel.startswith("router_desired__" if row[0] == "missing" else "router_seen__")
                       and key[0] == row[1] for rel, key in leaves)
    data["router_sweep"][0]["complete"] = True
    data["router_seen"][1]["first_port"] = data["router_seen"][1]["last_port"] = 8443
    assert compiled(data)[1].derived.get("managed_router_drift") == set()


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: Depends on the disposable router reader, shared router renderer and test_management_firewall_bidirectional. "
    "Read decisions/platform-management-firewall.md and compare an actual complete table read to the intended rows."))
def test_management_firewall_readback(monkeypatch):
    from case_support import ROOT
    from management_probes import live_events

    events = live_events("firewall")
    desired, = [e for e in events if e["kind"] == "desired-router-publication"]
    read, = [e for e in events if e["kind"] == "complete-router-read"]
    assert desired["router"] == read["router"] and desired["table"] == read["table"] and read["complete"] is True
    monkeypatch.syspath_prepend(str(ROOT.parents[1] / "loop"))
    from router_render import render

    assert hashlib.sha256(render(desired["rules"])).hexdigest() == desired["applied_sha256"]
    def keys(rules):
        return {(r["sourceFrom"], r["sourceTo"], r["destinationAddress"], r["protocol"], r["fromPort"], r["toPort"]) for r in rules}
    wanted, actual = keys(desired["rules"]), keys(read["rules"])
    assert len(wanted - actual) == len(actual - wanted) == 1
    findings = [e for e in events if e["kind"] == "router-drift"]
    assert {(e["direction"], tuple(e["rule"])) for e in findings} == (
        {("extra", key) for key in actual - wanted} | {("missing", key) for key in wanted - actual})
    assert all({desired["evidence"], read["evidence"]} <= set(e["source_evidence"]) for e in findings)
