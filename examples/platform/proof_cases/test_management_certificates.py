"""Check presented identities against caller-specific trust and a fixed evaluation date."""

import pytest

from case_support import imported, verified


def certificate_inputs():
    sites = ("near", "missing", "wrong", "untrusted", "future", "expired", "renewed", "unread", "plain")
    records = {
        "tls_requirement": [{"id": site, "caller": "client", "name": f"{site}.example.org",
                             "transport": "plain" if site == "plain" else "tls"} for site in sites],
        "tls_clock": [{"id": "policy", "day": "2026-06-10", "warning_days": 7}],
        "tls_root": [{"id": "client-trust", "caller": "client", "authority": "root"},
                     {"id": "other-trust", "caller": "other", "authority": "foreign"}],
        "tls_issuer": [{"id": "intermediate", "issuer": "root"}],
        "tls_read": [{"id": f"read-{s}", "service": s, "complete": True} for s in sites if s != "unread"],
        "tls_leaf": [],
    }
    for site in ("near", "wrong", "untrusted", "future", "expired", "renewed"):
        records["tls_leaf"].append({
            "id": f"presented-{site}", "service": site, "read": f"read-{site}",
            "dns_name": "another.example.org" if site == "wrong" else f"{site}.example.org",
            "issuer": "foreign" if site == "untrusted" else "intermediate",
            "begins": "2026-06-11" if site == "future" else "2026-06-01",
            "ends": {"near": "2026-06-17", "expired": "2026-06-10"}.get(site, "2026-09-01"),
        })
    return records


def test_management_certificate_findings():
    from management_probes import compiled

    data = certificate_inputs()
    for name_matches in (False, True):
        if name_matches:
            next(cert for cert in data["tls_leaf"] if cert["service"] == "wrong")["dns_name"] = "wrong.example.org"
        model, state = compiled(data)
        base = {("near", "expiring"), ("missing", "missing"), ("untrusted", "untrusted-chain"),
                ("future", "not-yet-valid"), ("expired", "expired")}
        assert state.derived.get("managed_tls_finding") == base | (set() if name_matches else {("wrong", "wrong-name")})
        assert state.derived.get("managed_tls_unknown") == {("unread",)}
        leaves = verified("managed_tls_finding", ("missing", "missing"), state=(model, state))
        assert any(rel.startswith("tls_read__") and key[0] == "read-missing" for rel, key in leaves)
    imported("std-time")


@pytest.mark.parametrize("clocks", [
    [],
    [
        {"id": "policy-a", "day": "2026-06-10", "warning_days": 7},
        {"id": "policy-b", "day": "2026-06-11", "warning_days": 7},
    ],
], ids=["missing-clock", "duplicate-clock"])
def test_management_certificate_missing_or_duplicate_clock_marks_presented_leaves_unknown(clocks):
    from management_probes import compiled

    data = certificate_inputs()
    data["tls_clock"] = clocks
    _, state = compiled(data)
    assert state.derived.get("managed_tls_finding") == {
        ("missing", "missing"), ("wrong", "wrong-name"), ("untrusted", "untrusted-chain"),
    }
    assert state.derived.get("managed_tls_unknown") == {
        ("unread",), ("near",), ("wrong",), ("untrusted",), ("future",), ("expired",), ("renewed",),
    }


@pytest.mark.cluster
def test_management_certificate_renewal_readback():
    from management_probes import live_events

    events = live_events("certificates")
    before, after = [e for e in events if e["kind"] == "tls-peer-observed"]
    assert before["caller"] == after["caller"] and before["expected_name"] == after["expected_name"] == "renewed.example.org"
    assert before["leaf_sha256"] != after["leaf_sha256"] and all(len(e["leaf_sha256"]) == 64 for e in (before, after))
    assert before["issuer_root_sha256"] == after["issuer_root_sha256"]
    assert all(e["verified_dns_name"] == e["expected_name"] and e["verified_chain"] for e in (before, after))
    renewal, = [e for e in events if e["kind"] == "renewal-applied"]
    assert events.index(before) < events.index(renewal) < events.index(after)
    result, = [e for e in events if e["kind"] == "renewal-judgement"]
    assert result["source_evidence"] == after["evidence"] and result["findings"] == []
