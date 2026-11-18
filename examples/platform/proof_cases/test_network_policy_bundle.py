import pytest

from case_support import ROOT


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Implement the single shared renderer in examples/platform/network_policy.py. Read decisions/platform-firewall-output.md. Admission consumes this same callable.')
def test_network_policy_bundle():
    import importlib.util
    path = ROOT / "network_policy.py"
    assert path.is_file(), "Missing shared NetworkPolicy renderer"
    spec = importlib.util.spec_from_file_location("network_policy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    flow = dict(source="reader", destination="web", protocol="TCP", fromPort=443, toPort=443)
    bundle = list(module.render_network_policies("blue", [flow]))
    assert len({m["metadata"]["name"] for m in bundle}) == len(bundle)
    assert all((m["apiVersion"], m["kind"], m["metadata"]["namespace"]) ==
               ("networking.k8s.io/v1", "NetworkPolicy", "blue") for m in bundle)
    baseline, = [m["spec"] for m in bundle if m["spec"]["podSelector"] == {}]
    assert set(baseline["policyTypes"]) == {"Ingress", "Egress"}
    assert not baseline.get("ingress") and not baseline.get("egress")
    grants = []
    for manifest in bundle:
        policy = manifest["spec"]
        for direction, peer in (("ingress", "from"), ("egress", "to")):
            for rule in policy.get(direction, []):
                selected = policy["podSelector"]
                other, = rule[peer]
                ports, = rule["ports"]
                grants.append((direction, selected, other, ports))
    def selector(service):
        return {"matchLabels": {"rezono.org/service": service}}
    port = {"protocol": "TCP", "port": 443}
    assert sorted(grants, key=lambda row: row[0]) == [
        ("egress", selector("reader"), {"podSelector": selector("web")}, port),
        ("ingress", selector("web"), {"podSelector": selector("reader")}, port)]
