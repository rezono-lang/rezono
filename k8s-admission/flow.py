"""Offline preflight for published same-namespace TCP flows."""

from itertools import product


SERVICE_LABEL = "app.kubernetes.io/name"


def _service(selector):
    if not isinstance(selector, dict) or selector.keys() != {"matchLabels"}:
        return None
    labels = selector["matchLabels"]
    if not isinstance(labels, dict) or labels.keys() != {SERVICE_LABEL}:
        return None
    value = labels[SERVICE_LABEL]
    if isinstance(value, str) and value:
        return value
    return None


def _port(entry):
    if not isinstance(entry, dict) or entry.keys() - {"protocol", "port"}:
        return None
    if entry.get("protocol", "TCP") != "TCP":
        return None
    value = entry.get("port")
    if type(value) is int and 1 <= value <= 65535:
        return value
    return None


def evaluate_ingress(policy, publication):
    """Check each requested peer and port pair against its complete tuple."""
    digest = publication.get("digest") if isinstance(publication, dict) else None
    if not isinstance(digest, str) or not digest:
        return {"allowed": False, "message": "in-zone-flow: missing publication digest"}

    def deny(reason):
        return {"allowed": False, "message": f"in-zone-flow ({digest}): {reason}"}

    if not isinstance(policy, dict) or policy.keys() != {"apiVersion", "kind", "metadata", "spec"}:
        return deny("unsupported policy shape")
    if policy["apiVersion"] != "networking.k8s.io/v1" or policy["kind"] != "NetworkPolicy":
        return deny("unsupported policy kind")
    metadata = policy["metadata"]
    namespace = publication.get("namespace")
    if not namespace or not isinstance(metadata, dict) or metadata.get("namespace") != namespace:
        return deny("no publication for the policy namespace")

    spec = policy["spec"]
    if not isinstance(spec, dict) or spec.keys() - {"policyTypes", "podSelector", "ingress"}:
        return deny("unsupported policy spec")
    if spec.get("policyTypes") != ["Ingress"]:
        return deny("expected ingress-only policyTypes")
    destination = _service(spec.get("podSelector"))
    if destination is None:
        return deny("missing or unsupported target service label")
    ingress = spec.get("ingress", [])
    if not isinstance(ingress, list):
        return deny("expected an ingress list")

    published = publication.get("flows")
    if not isinstance(published, list):
        return deny("missing publication flow list")
    allowed = set()
    for flow in published:
        if not isinstance(flow, dict) or flow.keys() != {"source", "destination", "port"}:
            return deny("invalid published flow")
        source, target, port = flow["source"], flow["destination"], flow["port"]
        if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
            return deny("invalid published flow service")
        if _port({"port": port}) is None:
            return deny("invalid published flow port")
        allowed.add((source, target, port))

    for rule in ingress:
        if not isinstance(rule, dict) or rule.keys() != {"from", "ports"}:
            return deny("expected explicit ingress peers and ports")
        peers, ports = rule["from"], rule["ports"]
        if not isinstance(peers, list) or not peers or not isinstance(ports, list) or not ports:
            return deny("expected nonempty ingress peers and ports")
        sources = []
        for peer in peers:
            if not isinstance(peer, dict) or peer.keys() != {"podSelector"}:
                return deny("expected a same-namespace pod peer")
            source = _service(peer["podSelector"])
            if source is None:
                return deny("missing or unsupported peer service label")
            sources.append(source)
        numbers = [_port(port) for port in ports]
        if None in numbers:
            return deny("expected numeric TCP ports without ranges")
        for source, port in product(sources, numbers):
            if (source, destination, port) not in allowed:
                return deny(f"unpublished flow {source} -> {destination}:{port}")
    return {"allowed": True, "message": f"in-zone-flow ({digest}): allowed"}
