"""Require the indexed manifest and exact rendered Kubernetes object identity."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement loop/readback_identity.py. Require the indexed manifest and exact rendered Kubernetes object identity.")
def test_readback_identity(monkeypatch):
    verify_identity = entry(monkeypatch, "readback_identity", "verify_identity")
    ref = {"manifest": "m-a", "apiVersion": "v1", "kind": "ConfigMap", "namespace": "fixture", "name": "echo"}
    obj = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"namespace": "fixture", "name": "echo"}}
    assert verify_identity(ref, "m-a", obj) is None
    for manifest, candidate in [("m-b", obj), ("m-a", {**obj, "kind": "Secret"}),
                                ("m-a", {**obj, "metadata": {"name": "echo", "namespace": "other"}})]:
        with pytest.raises(ValueError):
            verify_identity(ref, manifest, candidate)
