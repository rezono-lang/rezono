"""Render the modeled service grants for one namespace as NetworkPolicies."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rezono_publisher.retained_calculation import StoreReader


_NAMESPACE = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?")
_SERVICE = re.compile(r"[A-Za-z0-9](?:[-_.A-Za-z0-9]{0,61}[A-Za-z0-9])?")


def _selector(service: str) -> dict:
    return {"matchLabels": {"rezono.org/service": service}}


def _manifest(namespace: str, name: str, spec: dict) -> dict:
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }


def _grant(flow: Mapping[str, object]) -> tuple[str, str, str, int, int]:
    source, destination = flow.get("source"), flow.get("destination")
    if not isinstance(source, str) or not _SERVICE.fullmatch(source):
        raise ValueError("invalid source service identity")
    if not isinstance(destination, str) or not _SERVICE.fullmatch(destination):
        raise ValueError("invalid destination service identity")
    protocol = flow.get("protocol")
    if protocol not in ("TCP", "UDP", "SCTP"):
        raise ValueError("unsupported NetworkPolicy protocol")
    start, end = flow.get("fromPort"), flow.get("toPort")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= 65535:
        raise ValueError("expected an inclusive numeric port interval")
    return source, destination, protocol, start, end


def render_network_policies(
    namespace: str, flows: Iterable[Mapping[str, object]]
) -> list[dict]:
    """Return a deny-all baseline and paired allowances for each distinct grant."""
    if not _NAMESPACE.fullmatch(namespace):
        raise ValueError("invalid NetworkPolicy namespace")
    bundle = [_manifest(namespace, "rezono-default-deny", {
        "podSelector": {}, "policyTypes": ["Ingress", "Egress"],
    })]
    for grant in sorted({_grant(flow) for flow in flows}):
        source, destination, protocol, start, end = grant
        key = hashlib.sha256(json.dumps(grant, separators=(",", ":")).encode("utf-8")).hexdigest()
        for direction, peer_key, local, peer in (
            ("Ingress", "from", destination, source),
            ("Egress", "to", source, destination),
        ):
            ports = {"protocol": protocol, "port": start}
            if end != start:
                ports["endPort"] = end
            rules = [{peer_key: [{"podSelector": _selector(peer)}], "ports": [ports]}]
            field = direction.lower()
            bundle.append(_manifest(namespace, f"rezono-{field}-{key[:32]}", {
                "podSelector": _selector(local), "policyTypes": [direction], field: rules,
            }))
    return bundle


def render_published_network_policies(
    namespace: str, store: StoreReader, manifest: dict, role: str
) -> list[dict]:
    """Render only the listener grants in the checked publication for the reading role."""
    from rezono_checker.snapshots import read_rows
    from rezono_ports import refusal
    from rezono_publisher.publish import PROOFS
    from rezono_publisher.views import key_of

    reason = refusal(manifest)
    if reason:
        raise ValueError(reason)
    if [check["status"] for check in manifest["checks"] if check["name"] == PROOFS] != ["green"]:
        raise ValueError("publication needs a successful proof check")

    entries = [entry for entry in manifest["snapshots"]
               if entry["role"] == role and entry["relation"] == "listener_case_decision"]
    if len(entries) != 1:
        raise ValueError("expected one listener decision snapshot for the reading role")
    entry, = entries
    key = key_of(entry["uri"])
    if store.uri(key) != entry["uri"]:
        raise ValueError("listener snapshot is outside the publication store")
    data = store.get(key)
    if data is None or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("listener snapshot digest mismatch")

    flows = []
    for (source, destination, protocol, port, decision), _ in read_rows(data, entry["format"]).values():
        if decision == "allowed":
            if not re.fullmatch(r"[1-9][0-9]{0,4}", port):
                raise ValueError("expected a canonical listener port")
            flows.append({"source": source, "destination": destination, "protocol": protocol,
                          "fromPort": int(port), "toPort": int(port)})
    return render_network_policies(namespace, flows)
