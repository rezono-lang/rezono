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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/code-does-not-decide.md, section 4, and decisions/k8s-admission-translator.md, 'Order'. "
        "render_release in k8s-admission/admission_release.py renders each ValidatingAdmissionPolicy with "
        "admission_translator.translate from the checked rule program and binding of its rule "
        "(fixtures/translator/<rule>.rules.yaml and <rule>.binding.yaml), no longer with "
        "policy_renderer.render_policy, which then stays only as the expectation of test_translated_policy. The "
        "outcomes are the hand-calculated cases of decisions/k8s-admission-rules.md. admission_release.py is not a "
        "test: if k8s-admission/ is on the review-before-landing list by then, the switch is read before it "
        "lands. Today the release ships the hand-written policy (AssertionError)."
    ),
)
def test_release_renders_the_translated_policy(tmp_path):
    from admission_release import render_release
    from admission_translator import translate

    publication = load("publication.yaml")
    store = publish_evidence(tmp_path / "checked")
    release = render_release(["admission-blue", "admission-green"], [publication], store=store,
                             manifest_key=MANIFEST_KEY)
    digest, = {item["spec"]["digest"] for item in release if item["kind"] == "NamespacePublication"}
    policies = {item["metadata"]["name"].split(".")[0]: item for item in release
                if item["kind"] == "ValidatingAdmissionPolicy"}
    assert sorted(policies) == ["in-zone-flow", "verified-supply"]
    for rule, policy in sorted(policies.items()):
        expected = translate(load_program(f"{rule}.rules.yaml"), fixture(f"{rule}.binding.yaml"), digest)
        assert policy == expected, f"{rule}: the release does not ship the translated policy"

    path = tmp_path / "release.json"
    path.write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": release}), encoding="utf-8")
    for driver in ("cel", "apiserver"):
        for label, obj, expected in cases():
            proc = subprocess.run(["go", "run", ".", "--release", str(path)], cwd=ROOT / "oracles" / driver,
                                  input=json.dumps(review(obj)), text=True, capture_output=True, timeout=300,
                                  check=False)
            assert proc.returncode == 0, proc.stderr
            assert json.loads(proc.stdout)["response"]["allowed"] is expected, (driver, label)
