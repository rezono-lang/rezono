"""Compose a desired admission release from canonical namespace publications."""

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from bindings import MANAGED_NAMESPACE_LABEL, RULES, render_binding
from parameter_reader import read_parameters
from policy_renderer import render_policy


def render_release(namespaces: Iterable[str], publications: Iterable[dict]) -> list[dict]:
    """Return the CRD, managed namespaces, publications and two policy/binding pairs."""
    managed: set[str] = set()
    for namespace in namespaces:
        if not isinstance(namespace, str) or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
            raise ValueError("expected a DNS label for the managed namespace")
        if namespace in managed:
            raise ValueError(f"duplicate managed namespace: {namespace}")
        managed.add(namespace)

    by_namespace: dict[str, dict] = {}
    release_identities: set[tuple[str, str]] = set()
    for publication in publications:
        if not isinstance(publication, dict) or publication.get("kind") != "NamespacePublication":
            raise ValueError("expected a canonical NamespacePublication")
        metadata = publication.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("publication must have metadata")
        namespace, name = metadata.get("namespace"), metadata.get("name")
        if not isinstance(namespace, str) or namespace not in managed:
            raise ValueError("publication must belong to a managed namespace")
        if not isinstance(name, str):
            raise ValueError("publication must have a parameter name")
        if namespace in by_namespace:
            raise ValueError(f"ambiguous publications for namespace: {namespace}")
        parameters = read_parameters(namespace, publication)
        by_namespace[namespace] = publication
        release_identities.add((parameters["digest"], name))

    # Each binding matches every managed namespace and resolves the same parameter name there.
    if len(release_identities) != 1:
        raise ValueError("expected exactly one publication digest and parameter name for the release")
    ((digest, name),) = release_identities
    crd_path = Path(__file__).with_name("resources") / "publication-crd.yaml"
    crd = yaml.safe_load(crd_path.read_text(encoding="utf-8"))
    resources = [crd]
    resources.extend({
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": namespace, "labels": {MANAGED_NAMESPACE_LABEL: "enabled"}},
    } for namespace in sorted(managed))
    resources.extend(by_namespace[namespace] for namespace in sorted(by_namespace))
    for rule in sorted(RULES):
        resources.append(render_policy(rule=rule, digest=digest))
        resources.append(render_binding(rule=rule, digest=digest, parameter_name=name))
    return resources
