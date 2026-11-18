"""Render a normalized tenant catalog row as a Backstage component."""

from typing import Literal, TypedDict


class ComponentMetadata(TypedDict):
    namespace: str
    name: str


class ComponentSpec(TypedDict):
    type: Literal["service"]
    lifecycle: str
    owner: str


class Component(TypedDict):
    apiVersion: Literal["backstage.io/v1alpha1"]
    kind: Literal["Component"]
    metadata: ComponentMetadata
    spec: ComponentSpec


def render(tenant: str, service: str, profile: str) -> Component:
    return {
        "apiVersion": "backstage.io/v1alpha1",
        "kind": "Component",
        "metadata": {"namespace": tenant, "name": service},
        "spec": {"type": "service", "lifecycle": profile, "owner": f"group:{tenant}/{tenant}"},
    }
