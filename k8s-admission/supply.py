"""Offline preflight for the verified-supply admission rule."""

import re


_SERVICE_LABEL = "app.kubernetes.io/name"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")


def evaluate_pod(pod: dict, publication: dict) -> dict[str, bool | str]:
    """Check every Pod image against the publication for its namespace and service."""
    digest = publication.get("digest")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        return {"allowed": False, "message": "verified-supply: missing or invalid publication digest"}
    diagnostic = f"verified-supply publication {digest}"

    metadata = pod.get("metadata")
    if not isinstance(metadata, dict):
        return {"allowed": False, "message": f"{diagnostic}: missing Pod metadata"}
    namespace = metadata.get("namespace")
    if not isinstance(namespace, str) or not namespace or namespace != publication.get("namespace"):
        return {"allowed": False, "message": f"{diagnostic}: no publication for Pod namespace"}
    labels = metadata.get("labels")
    service = labels.get(_SERVICE_LABEL) if isinstance(labels, dict) else None
    if not isinstance(service, str) or not service:
        return {"allowed": False, "message": f"{diagnostic}: missing {_SERVICE_LABEL} service label"}

    entries = publication.get("images")
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        return {"allowed": False, "message": f"{diagnostic}: invalid publication images"}
    spec = pod.get("spec")
    if not isinstance(spec, dict) or not spec.get("containers"):
        return {"allowed": False, "message": f"{diagnostic}: missing Pod containers"}
    for group in ("containers", "initContainers", "ephemeralContainers"):
        containers = spec.get(group, [])
        if not isinstance(containers, list):
            return {"allowed": False, "message": f"{diagnostic}: invalid Pod {group}"}
        for container in containers:
            image = container.get("image") if isinstance(container, dict) else None
            if not isinstance(image, str) or not image:
                return {"allowed": False, "message": f"{diagnostic}: missing image in {group}"}
            if not _IMAGE.fullmatch(image) or not any(
                entry.get("service") == service and entry.get("image") == image for entry in entries
            ):
                return {"allowed": False, "message": f"{diagnostic}: unverified image in {group}"}
    return {"allowed": True, "message": ""}
