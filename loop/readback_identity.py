"""Bind a read-back object to its indexed manifest and resource identity."""

from collections.abc import Mapping


def verify_identity(
    reference: Mapping[str, object], manifest: str, obj: Mapping[str, object]
) -> None:
    """Require the exact manifest, API version, kind, namespace and name."""
    metadata = obj.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("read-back object requires metadata")

    observed = {
        "manifest": manifest,
        "apiVersion": obj.get("apiVersion"),
        "kind": obj.get("kind"),
        "namespace": metadata.get("namespace"),
        "name": metadata.get("name"),
    }
    for field, value in observed.items():
        if not isinstance(value, str) or not value.strip() or reference.get(field) != value:
            raise ValueError(f"read-back {field} must match the indexed identity")
