"""Offline preflight for the renderer's managed NetworkPolicies."""

import re
from itertools import product

from flow import _port


_SERVICE_LABEL = "rezono.org/service"
_DIRECTIONS = {"Ingress": ("ingress", "from"), "Egress": ("egress", "to")}


def _service(selector):
    if not isinstance(selector, dict) or selector.keys() != {"matchLabels"}:
        return None
    labels = selector["matchLabels"]
    if not isinstance(labels, dict) or labels.keys() != {_SERVICE_LABEL}:
        return None
    value = labels[_SERVICE_LABEL]
    return value if isinstance(value, str) and value else None


def _port_range(entry):
    if not isinstance(entry, dict) or entry.keys() - {"protocol", "port", "endPort"}:
        raise ValueError("expected explicit numeric TCP ports")
    start = _port({"protocol": entry.get("protocol", "TCP"), "port": entry.get("port")})
    end = entry.get("endPort", start)
    if start is None or type(end) is not int or not start <= end <= 65535:
        raise ValueError("expected a valid numeric TCP port or range")
    return range(start, end + 1)


def _published_flows(publication):
    flows = publication.get("flows")
    if not isinstance(flows, list):
        raise ValueError("missing publication flow list")
    tuples = set()
    for flow in flows:
        if not isinstance(flow, dict) or flow.keys() != {"source", "destination", "port"}:
            raise ValueError("invalid published flow")
        source, destination, port = flow["source"], flow["destination"], flow["port"]
        if not all(isinstance(service, str) and service for service in (source, destination)):
            raise ValueError("invalid published service")
        if _port({"port": port}) is None:
            raise ValueError("invalid published flow port")
        tuples.add((source, destination, port))
    return tuples


def _check_rules(rules, peer_key, local, allowed):
    for rule in rules:
        if not isinstance(rule, dict) or rule.keys() != {peer_key, "ports"}:
            raise ValueError("expected explicit peers and ports")
        peers, ports = rule[peer_key], rule["ports"]
        if not isinstance(peers, list) or not peers or not isinstance(ports, list) or not ports:
            raise ValueError("expected nonempty peer and port lists")
        services = []
        for peer in peers:
            if not isinstance(peer, dict) or peer.keys() != {"podSelector"}:
                raise ValueError("expected a same-namespace pod peer")
            service = _service(peer["podSelector"])
            if service is None:
                raise ValueError("missing or unsupported peer service label")
            services.append(service)
        ranges = [_port_range(port) for port in ports]
        for peer, interval in product(services, ranges):
            source, destination = (peer, local) if peer_key == "from" else (local, peer)
            for port in interval:
                if (source, destination, port) not in allowed:
                    raise ValueError(f"unpublished flow {source} -> {destination}:{port}")


def evaluate_network_policy(policy: dict, publication: dict) -> dict[str, bool | str]:
    """Require every ingress and egress tuple to match its namespace publication."""
    digest = publication.get("digest") if isinstance(publication, dict) else None
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return {"allowed": False, "message": "in-zone-flow: missing or invalid publication digest"}
    message = f"in-zone-flow ({digest})"
    try:
        if not isinstance(policy, dict) or policy.keys() != {"apiVersion", "kind", "metadata", "spec"}:
            raise ValueError("unsupported policy shape")
        if policy["apiVersion"] != "networking.k8s.io/v1" or policy["kind"] != "NetworkPolicy":
            raise ValueError("unsupported policy kind")
        metadata, namespace = policy["metadata"], publication.get("namespace")
        if not isinstance(namespace, str) or not namespace or not isinstance(metadata, dict) or metadata.get("namespace") != namespace:
            raise ValueError("no publication for the policy namespace")

        spec = policy["spec"]
        if not isinstance(spec, dict) or spec.keys() - {"podSelector", "policyTypes", "ingress", "egress"}:
            raise ValueError("unsupported policy spec")
        policy_types = spec.get("policyTypes")
        if (not isinstance(policy_types, list) or not policy_types
                or any(not isinstance(direction, str) or direction not in _DIRECTIONS
                       for direction in policy_types)
                or len(set(policy_types)) != len(policy_types)):
            raise ValueError("expected explicit ingress or egress policy types")
        ingress, egress = spec.get("ingress", []), spec.get("egress", [])
        if not isinstance(ingress, list) or not isinstance(egress, list):
            raise ValueError("expected ingress and egress rule lists")
        allowed = _published_flows(publication)
        selector = spec.get("podSelector")
        if selector == {}:
            if ingress or egress or set(policy_types) != set(_DIRECTIONS):
                raise ValueError("a namespace-wide baseline requires both policy types and no rules")
        else:
            local = _service(selector)
            if local is None:
                raise ValueError("missing or unsupported local service label")
            for direction, (field, peer_key) in _DIRECTIONS.items():
                rules = spec.get(field, [])
                if rules and direction not in policy_types:
                    raise ValueError(f"{field} rules require {direction} policy type")
                _check_rules(rules, peer_key, local, allowed)
    except ValueError as error:
        return {"allowed": False, "message": f"{message}: {error}"}
    return {"allowed": True, "message": f"{message}: allowed"}
