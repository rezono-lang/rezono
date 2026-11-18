"""Compose a desired admission release from canonical namespace publications."""

from copy import deepcopy
from hashlib import sha256
import json
import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from rezono_checker.snapshots import read_rows
from rezono_publisher.views import key_of

from bindings import MANAGED_NAMESPACE_LABEL, RULES, render_binding
from parameter_reader import read_parameters
from policy_renderer import render_policy


def _checked_rows(store, manifest_key: str):
    raw = store.get(manifest_key)
    if raw is None:
        raise ValueError("checked publication manifest is missing")
    manifest = json.loads(raw)
    checks = manifest.get("checks", [])
    if ([check["status"] for check in checks if check["name"] == "rezono:proofs"] != ["green"]
            or any(check["status"] != "green" for check in checks)):
        raise ValueError("publication needs a successful proof check")

    rows = {}
    for relation in ("admission_flow", "image_build", "image_signature"):
        entries = [entry for entry in manifest["snapshots"]
                   if entry["role"] == "checker" and entry["relation"] == relation]
        if len(entries) != 1 or entries[0]["complete"] is not True:
            raise ValueError(f"expected one complete checker snapshot for {relation}")
        entry, = entries
        key = key_of(entry["uri"])
        if store.uri(key) != entry["uri"]:
            raise ValueError(f"checker snapshot outside the publication store: {relation}")
        data = store.get(key)
        if data is None or sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"checker snapshot digest mismatch: {relation}")
        rows[relation] = {parts for parts, _ in read_rows(data, entry["format"]).values()}
    return sha256(raw).hexdigest(), rows["admission_flow"], rows["image_build"] & rows["image_signature"]


def render_release(namespaces: Iterable[str], publications: Iterable[dict], *, store, manifest_key: str) -> list[dict]:
    """Return the CRD, managed namespaces, publications and two policy/binding pairs."""
    digest, checked_flows, checked_images = _checked_rows(store, manifest_key)
    managed: set[str] = set()
    for namespace in namespaces:
        if not isinstance(namespace, str) or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", namespace):
            raise ValueError("expected a DNS label for the managed namespace")
        if namespace in managed:
            raise ValueError(f"duplicate managed namespace: {namespace}")
        managed.add(namespace)

    by_namespace: dict[str, dict] = {}
    parameter_names: set[str] = set()
    for publication in publications:
        if not isinstance(publication, dict) or publication.get("kind") != "NamespacePublication":
            raise ValueError("expected a canonical NamespacePublication")
        publication = deepcopy(publication)
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
        if parameters["digest"] != digest:
            raise ValueError("release digest differs from the checked publication")
        flows = {(namespace, row["source"], row["destination"], "TCP", str(row["port"]))
                 for row in parameters["flows"]}
        flows.update((namespace, row["source"], row["destination"], row["protocol"], str(row["port"]))
                     for row in parameters.get("transportFlows", []))
        if flows != {row for row in checked_flows if row[0] == namespace}:
            raise ValueError("flow rows differ from the checked publication")
        images = {(namespace, row["service"], row["image"]) for row in parameters["images"]}
        if images != {row for row in checked_images if row[0] == namespace}:
            raise ValueError("image rows differ from the checked publication")
        by_namespace[namespace] = publication
        parameter_names.add(name)

    # Each binding matches every managed namespace and resolves the same parameter name there.
    if len(parameter_names) != 1:
        raise ValueError("expected exactly one publication digest and parameter name for the release")
    (name,) = parameter_names
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
