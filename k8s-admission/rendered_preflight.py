"""Evaluate a rendered NetworkPolicy bundle against one namespace publication."""

from collections.abc import Iterable
import re

from managed_network_policy import evaluate_network_policy


def assess_rendered_policies(
    manifests: Iterable[dict], publication: dict
) -> dict[str, dict[str, bool | str]]:
    """Return each named policy's decision bound to the supplied release digest."""
    digest, namespace = publication.get("digest"), publication.get("namespace")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid namespace publication digest")
    if not isinstance(namespace, str) or not namespace:
        raise ValueError("missing publication namespace")

    results = {}
    for manifest in manifests:
        metadata = manifest.get("metadata") if isinstance(manifest, dict) else None
        name = metadata.get("name") if isinstance(metadata, dict) else None
        if not isinstance(name, str) or not name:
            raise ValueError("rendered policy requires a name")
        if name in results:
            raise ValueError(f"duplicate rendered policy name: {name}")
        decision = evaluate_network_policy(manifest, publication)
        results[name] = {"allowed": decision["allowed"], "digest": digest}
    return results
