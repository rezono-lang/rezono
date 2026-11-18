"""Replay real platform grants against the released, hand-written CEL rule."""

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).parent.resolve()
PROTOCOLS = ("TCP", "UDP", "SCTP")


def release_for(protocol):
    from admission_release import render_release

    template = ROOT / "fixtures" / "blue-namespace-publication.yaml"
    publication = yaml.safe_load(template.read_text(encoding="utf-8"))
    spec = publication["spec"]
    # A different release authorizes each transport for the very same service pair and port.
    spec["digest"] = {"TCP": "a", "UDP": "b", "SCTP": "c"}[protocol] * 64
    row = {"source": "idp", "destination": "dns", "port": 53}
    spec["flows"] = [row] if protocol == "TCP" else []
    if protocol != "TCP":
        spec["transportFlows"] = [dict(row, protocol=protocol)]
    items = list(render_release(["blue"], [publication]))
    return {"apiVersion": "v1", "kind": "List", "items": items}, spec["digest"]


def review_for(manifest):
    group = "networking.k8s.io"
    return {
        "apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview",
        "request": {
            "uid": "ec332ceb-ec68-4c5b-a93c-ee22ac4129ca", "operation": "CREATE",
            "kind": {"group": group, "version": "v1", "kind": "NetworkPolicy"},
            "resource": {"group": group, "version": "v1", "resource": "networkpolicies"},
            "namespace": "blue", "name": manifest["metadata"]["name"],
            "userInfo": {"username": "fixture-reader"}, "dryRun": True, "object": manifest,
        },
    }


@pytest.mark.xfail(strict=True, raises=(AssertionError, ModuleNotFoundError), reason="Depends on the platform generator, typed transport publication, desired release and standalone CEL oracle. Update both directions in k8s-admission/policy_renderer.py per decisions/k8s-admission-transport.md.")
def test_manual_cel_matches_generated_transport_grants(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT.parent / "examples" / "platform"))
    from network_policy import render_network_policies

    oracle = ROOT / "oracles" / "cel"
    assert oracle.is_dir(), "The standalone CEL oracle is required."
    executable = tmp_path / ("cel.exe" if os.name == "nt" else "cel")
    subprocess.run(["go", "build", "-o", str(executable), "."], cwd=oracle, check=True, timeout=180)
    release_file = tmp_path / "release.json"
    for published in PROTOCOLS:
        release, digest = release_for(published)
        release_file.write_text(json.dumps(release), encoding="utf-8")
        for requested in PROTOCOLS:
            flow = {"source": "idp", "destination": "dns", "fromPort": 53,
                    "toPort": 53, "protocol": requested}
            observed = []
            for manifest in render_network_policies("blue", [flow]):
                directions = tuple(sorted(manifest["spec"]["policyTypes"]))
                review = review_for(manifest)
                result = subprocess.run(
                    [str(executable), "--release", str(release_file)],
                    input=json.dumps(review), text=True, capture_output=True, check=True, timeout=30,
                )
                response = json.loads(result.stdout)["response"]
                assert response["uid"] == review["request"]["uid"]
                allowed = response["allowed"]
                assert type(allowed) is bool
                observed.append((directions, allowed))
                if not allowed:
                    message = response["status"]["message"]
                    assert "in-zone-flow" in message and digest in message
            # The default-deny baseline grants nothing. Only the published transport has a witness.
            expected = published == requested
            assert sorted(observed) == [
                (("Egress",), expected), (("Egress", "Ingress"), True), (("Ingress",), expected),
            ], (published, requested)
