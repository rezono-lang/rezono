"""Replay real platform grants against the released, hand-written CEL rule."""

import json
from hashlib import sha256
import os
from pathlib import Path
import subprocess

import pytest
import yaml
from checked_release_fixture import MANIFEST_KEY, publish_evidence


ROOT = Path(__file__).parent.resolve()
PROTOCOLS = ("TCP", "UDP", "SCTP")


def release_for(protocol, directory, ports=(53,)):
    from admission_release import render_release

    template = ROOT / "fixtures" / "blue-namespace-publication.yaml"
    publication = yaml.safe_load(template.read_text(encoding="utf-8"))
    spec = publication["spec"]
    # A different release authorizes each transport for the very same service pair and port.
    store = publish_evidence(directory, protocol, ports=ports)
    spec["digest"] = sha256(store.get(MANIFEST_KEY)).hexdigest()
    rows = [{"source": "idp", "destination": "dns", "port": port} for port in ports]
    spec["flows"] = rows if protocol == "TCP" else []
    if protocol != "TCP":
        spec["transportFlows"] = [dict(row, protocol=protocol) for row in rows]
    items = render_release(["blue"], [publication], store=store, manifest_key=MANIFEST_KEY)
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


def test_transport_coverage_in_both_released_directions(tmp_path, monkeypatch):
    from managed_network_policy import evaluate_network_policy
    from parameter_reader import read_parameters

    monkeypatch.syspath_prepend(str(ROOT.parent / "examples" / "platform"))
    from network_policy import render_network_policies

    samples, expected, preflight, identities = [], [], [], []
    for published in PROTOCOLS:
        release, _ = release_for(published, tmp_path / published, (53, 54, 56))
        publication, = (r for r in release["items"] if r["kind"] == "NamespacePublication")
        policy, = (r["spec"] for r in release["items"] if r["kind"] == "ValidatingAdmissionPolicy"
                   and r["metadata"]["name"].startswith("in-zone-flow."))
        parameters = read_parameters("blue", publication)
        for requested in (*PROTOCOLS, None):
            for end, reverse in [(53, False), (54, False), (56, False), (53, True)]:
                source, destination = ("dns", "idp") if reverse else ("idp", "dns")
                flow = dict(source=source, destination=destination, protocol=requested or "TCP",
                            fromPort=53, toPort=end)
                for obj in render_network_policies("blue", [flow]):
                    directions = obj["spec"]["policyTypes"]
                    baseline = len(directions) == 2
                    if requested is None and not baseline:
                        del obj["spec"][directions[0].lower()][0]["ports"][0]["protocol"]
                    expected.append(baseline or (published == (requested or "TCP") and end <= 54 and not reverse))
                    preflight.append(evaluate_network_policy(obj, parameters)["allowed"])
                    identities.append((published, requested, end, reverse, directions))
                    samples.append({"object": obj, "params": publication, "variables": policy["variables"],
                                    "validations": policy["validations"]})
    probe = subprocess.run(["go", "run", "-mod=readonly", "."], cwd=ROOT / "oracles" / "flow-expression",
                           input=json.dumps(samples), text=True, capture_output=True, timeout=180)
    assert probe.returncode == 0, probe.stderr
    results = json.loads(probe.stdout)
    for identity, want, offline, cel in zip(identities, expected, preflight, results, strict=True):
        assert (offline, cel) == (want, want), identity


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
        release, digest = release_for(published, tmp_path / published)
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
