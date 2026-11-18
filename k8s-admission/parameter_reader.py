"""Read namespace publication parameters for offline preflight evaluation."""

import re

from transport_rule import EXPLICIT_PROTOCOLS


def read_parameters(namespace: str, resource: dict) -> dict:
    """Read typed policy inputs from a publication in the request namespace."""
    # The old spelling remains valid only for offline input.
    if (resource.get("apiVersion") != "admission.rezono.org/v1alpha1"
            or resource.get("kind") not in ("NamespacePublication", "AdmissionPublication")):
        raise ValueError("expected an admission.rezono.org/v1alpha1 NamespacePublication")

    metadata = resource.get("metadata")
    if not namespace or not isinstance(metadata, dict) or metadata.get("namespace") != namespace:
        raise ValueError("publication namespace must match the request namespace")

    spec = resource.get("spec")
    required = {"digest", "images", "flows"}
    if not isinstance(spec, dict) or not required <= spec.keys() <= required | {"transportFlows"}:
        raise ValueError("publication spec must contain digest, images and flows")
    digest, images, flows = spec["digest"], spec["images"], spec["flows"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("publication digest must be a lowercase SHA-256 digest")
    if not isinstance(images, list) or not isinstance(flows, list):
        raise ValueError("publication images and flows must be lists")

    for image in images:
        if not isinstance(image, dict) or set(image) != {"service", "image"}:
            raise ValueError("image entries require a service and image")
        if (not isinstance(image["service"], str) or not image["service"]
                or not isinstance(image["image"], str)
                or not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", image["image"])):
            raise ValueError("image entries require a service and digest-qualified image")
    for flow in flows:
        if not isinstance(flow, dict) or set(flow) != {"source", "destination", "port"}:
            raise ValueError("flow entries require source, destination and port")
        if (not all(isinstance(flow[key], str) and flow[key] for key in ("source", "destination"))
                or type(flow["port"]) is not int or not 1 <= flow["port"] <= 65535):
            raise ValueError("flow entries require named endpoints and a bounded integer port")

    if len({(entry["service"], entry["image"]) for entry in images}) != len(images):
        raise ValueError("publication contains duplicate image entries")
    if len({(entry["source"], entry["destination"], entry["port"]) for entry in flows}) != len(flows):
        raise ValueError("publication contains duplicate flow entries")

    result = {"namespace": namespace, "digest": digest, "images": images, "flows": flows}
    if "transportFlows" in spec:
        transport_flows = spec["transportFlows"]
        validate_transport_flows(transport_flows)
        result["transportFlows"] = transport_flows
    return result


def validate_transport_flows(rows: object) -> None:
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError("publication transportFlows must be a list of at most 256 entries")
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"source", "destination", "protocol", "port"}:
            raise ValueError("transport flow entries require source, destination, protocol and port")
        source, destination, protocol, port = (
            row["source"], row["destination"], row["protocol"], row["port"]
        )
        if (not all(isinstance(endpoint, str) and 1 <= len(endpoint) <= 63
                    for endpoint in (source, destination))
                or protocol not in EXPLICIT_PROTOCOLS or type(port) is not int or not 1 <= port <= 65535):
            raise ValueError("transport flow entries require named endpoints, UDP or SCTP and a bounded integer port")
        identity = (source, destination, protocol, port)
        if identity in identities:
            raise ValueError("publication contains duplicate transport flow entries")
        identities.add(identity)
