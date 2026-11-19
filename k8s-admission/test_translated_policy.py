"""The translated release decides every part 1 request as the hand-written release does.

See decisions/k8s-admission-translator.md, "Order". Each outcome is also stated by hand, from
decisions/k8s-admission-rules.md, so neither release is the other's only expectation.
"""

import json
import subprocess
from copy import deepcopy

import pytest
import yaml
from checked_release_fixture import MANIFEST_KEY, publish_evidence
from translator_support import FIXTURES, IMAGE_A, IMAGE_B, ROOT, fixture, load_program

SERVER = FIXTURES.parent / "server"


def load(name):
    return yaml.safe_load((SERVER / name).read_text(encoding="utf-8"))


def variant(obj, change):
    obj = deepcopy(obj)
    change(obj)
    return obj


def cases():
    pod, flow = load("pod.yaml"), load("flow.yaml")
    ingress = lambda obj: obj["spec"]["ingress"][0]
    green = lambda obj: obj["metadata"].update(namespace="admission-green")
    return [
        ("pod", pod, True),
        ("pod image B", variant(pod, lambda o: o["spec"]["containers"][0].update(image=IMAGE_B)), False),
        ("pod init A", variant(pod, lambda o: o["spec"].update(initContainers=[{"name": "init", "image": IMAGE_A}])),
         True),
        ("pod init B", variant(pod, lambda o: o["spec"].update(initContainers=[{"name": "init", "image": IMAGE_B}])),
         False),
        ("pod without service", variant(pod, lambda o: o["metadata"].pop("labels")), False),
        ("pod in green", variant(pod, green), False),
        ("flow", flow, True),
        ("flow 8443", variant(flow, lambda o: ingress(o)["ports"][0].update(port=8443)), False),
        ("flow from probe", variant(flow, lambda o: ingress(o)["from"][0]["podSelector"]["matchLabels"].update(
            {"rezono.org/service": "probe"})), False),
        ("flow UDP", variant(flow, lambda o: ingress(o)["ports"][0].update(protocol="UDP")), False),
        ("flow ip block", variant(flow, lambda o: ingress(o).update({"from": [{"ipBlock": {"cidr": "192.0.2.0/24"}}]})),
         False),
        ("baseline", variant(flow, lambda o: o.update(spec={"podSelector": {}, "policyTypes": ["Ingress", "Egress"]})),
         True),
        ("flow in green", variant(flow, green), False),
    ]


def review(obj):
    group, resource = ("", "pods") if obj["kind"] == "Pod" else ("networking.k8s.io", "networkpolicies")
    return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview",
            "request": {"uid": "5b0c6d4e-6c57-4b51-9d7c-2f0f4c1e9a10", "operation": "CREATE",
                        "kind": {"group": group, "version": "v1", "kind": obj["kind"]},
                        "resource": {"group": group, "version": "v1", "resource": resource},
                        "namespace": obj["metadata"]["namespace"], "name": obj["metadata"]["name"],
                        "userInfo": {"username": "fixture-reader"}, "object": obj, "dryRun": True}}


@pytest.mark.xfail(
    strict=True,
    reason="Compose admission_translator.translate from the translator blocks as decisions/k8s-admission-translator.md "
           "specifies under Order. Waits for test_cel_literal, test_cel_condition, test_cel_atom, test_cel_port_range, "
           "test_cel_parameter_tables, test_cel_request_sources, test_policy_shell and test_admission_route. "
           "Write in k8s-admission/admission_translator.py. Needs Go for both offline oracles.",
)
def test_translated_policy(tmp_path):
    from admission_release import render_release
    from admission_translator import translate

    publication = load("publication.yaml")
    store = publish_evidence(tmp_path / "checked")
    manual = render_release(["admission-blue", "admission-green"], [publication], store=store,
                            manifest_key=MANIFEST_KEY)
    digest, = {item["spec"]["digest"] for item in manual if item["kind"] == "NamespacePublication"}
    generated = []
    for item in manual:
        if item["kind"] == "ValidatingAdmissionPolicy":
            rule = item["metadata"]["name"].split(".")[0]
            item = translate(load_program(f"{rule}.rules.yaml"), fixture(f"{rule}.binding.yaml"), digest)
        generated.append(item)
    assert [item["metadata"]["name"] for item in generated] == [item["metadata"]["name"] for item in manual]

    releases = {}
    for name, items in (("manual", manual), ("generated", generated)):
        releases[name] = tmp_path / f"{name}.json"
        releases[name].write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": items}), encoding="utf-8")
    for driver in ("cel", "apiserver"):
        for label, obj, expected in cases():
            outcomes = []
            for name in ("manual", "generated"):
                proc = subprocess.run(["go", "run", ".", "--release", str(releases[name])], cwd=ROOT / "oracles" / driver,
                                      input=json.dumps(review(obj)), text=True, capture_output=True, timeout=300,
                                      check=False)
                assert proc.returncode == 0, proc.stderr
                response = json.loads(proc.stdout)["response"]
                outcomes.append(response["allowed"])
                # A missing parameter is denied by Kubernetes itself, which names the policy but not the digest.
                if not response["allowed"] and obj["metadata"]["namespace"] == "admission-blue":
                    rule = "verified-supply" if obj["kind"] == "Pod" else "in-zone-flow"
                    assert rule in response["status"]["message"] and digest in response["status"]["message"], label
            assert outcomes == [expected, expected], (driver, label)
