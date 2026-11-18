import pytest

from query_fixture import check_relation, evidence


def test_entry_tls_substitutes_only_the_selected_path():
    rows, _ = evidence()
    forbidden = {tuple(row) for row in rows["recovery_reaches_out"]}
    before = {tuple(row) for row in rows["flow"] if tuple(row[:3]) not in forbidden}
    direct = ("shop", "idp", "identity", 8443)
    assert direct in before
    after = (before - {direct}) | {("shop", "lb", "identity", 443), ("lb", "idp", "identity", 8080)}
    zones = dict(rows["zone_of"])
    def project(flows):
        return {(zones[a], zones[b], port) for a, b, _, port in flows if zones[a] != zones[b]}
    def delta(old, new):
        return {("removed", *r) for r in old - new} | {("added", *r) for r in new - old}
    assert ("removed", "tenant", "platform", 8443) not in delta(project(before), project(after))
    check_relation("entry_tls_flow_delta", delta(before, after))
    check_relation("entry_tls_firewall_delta", delta(project(before), project(after)))
