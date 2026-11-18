import pytest

from case_support import exact


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Implement finite listener decisions in examples/platform/schema/listener.yaml, facts/listener.yaml and rules/listener.dl. Read decisions/platform-derivation-acceptance.md. Evaluate the union before service isolation.")
def test_listener_decisions_after_all_grants():
    # A and B share a source range. The two independent firewall grants allow X and Y.
    # Z listens without a grant. Q has no listener. Only A has service permission for X and Y.
    allowed = {("a", "x"), ("a", "y")}
    firewall = {("a", "z"), ("b", "z")}
    service = {("b", "x"), ("b", "y")}
    rows = {(src, dst, "TCP", 443, result) for result, pairs in
            (("allowed", allowed), ("firewall", firewall), ("service-isolation", service))
            for src, dst in pairs}
    exact("listener_case_decision", rows)
