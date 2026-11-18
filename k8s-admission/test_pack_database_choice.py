"""Change the chosen database in the platform pack, then admit an unchanged set of policies."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from bindings import render_binding
from flow_projection import project_flows
from managed_network_policy import evaluate_network_policy
from parameter_reader import read_parameters
from policy_renderer import render_policy
from rezono_publisher import batch, publish, store
from rezono_publisher.views import key_of


ROOT = Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "examples" / "platform"
NAMESPACE = "platform"
CANDIDATES = (("idp", "db-idp"), ("idp", "db-git"), ("git", "db-git"))


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    work = tmp_path_factory.mktemp("database-choice")
    pack = work / "examples" / "platform"
    shutil.copytree(PLATFORM, pack)
    shutil.copytree(ROOT / "packs", work / "packs")
    assert json.loads((pack / "firewall-inputs.json").read_bytes())["protocols"]["database"] == "TCP"
    path = pack / "facts" / "core.yaml"
    facts = yaml.safe_load(path.read_bytes())
    choice, = (row for row in facts["choice"] if row["id"] == "c-idp-db")
    assert (choice["service"], choice["function"], choice["provider"]) == ("idp", "database", "db-idp")
    editions = []
    for target in ("db-idp", "db-git"):
        choice["provider"] = target
        path.write_text(yaml.safe_dump(facts, sort_keys=False), encoding="utf-8")
        epoch = batch.epoch(pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                            sources=[("facts", "database-choice")])
        bucket = store.FileStore(work / target)
        manifest = publish.publish(epoch, bucket, {"checker": "complete"})
        raw_manifest = bucket.get(f"{epoch.pack}/manifests/{manifest['id']}.json")
        digest = hashlib.sha256(raw_manifest).hexdigest()
        entry, = (e for e in json.loads(raw_manifest)["snapshots"]
                  if e["role"] == "checker" and e["relation"] == "in_zone_witness")
        raw = bucket.get(key_of(entry["uri"]))
        assert entry["complete"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]
        rows = (item["key"] for item in json.loads(raw))
        flows = project_flows(NAMESPACE, ((ns, src, dst, int(port)) for ns, src, dst, function, port in rows
                                         if function == "database"))
        resource = {"apiVersion": "admission.rezono.org/v1alpha1", "kind": "NamespacePublication",
                    "metadata": {"namespace": NAMESPACE, "name": "database"},
                    "spec": {"digest": digest, "images": [], "flows": flows}}
        editions.append((target, resource))
    return editions


def check_grants(releases, monkeypatch, *, explicit_empty):
    monkeypatch.syspath_prepend(str(PLATFORM))
    from network_policy import render_network_policies

    for target, resource in releases:
        params = read_parameters(NAMESPACE, resource)
        for source, destination in CANDIDATES:
            wanted = source == "git" or destination == target
            flow = {"source": source, "destination": destination, "protocol": "TCP",
                    "fromPort": 5432, "toPort": 5432}
            results = {}
            for obj in render_network_policies(NAMESPACE, [flow]):
                spec = obj["spec"]
                if len(spec["policyTypes"]) == 1:
                    direction, = spec["policyTypes"]
                    if explicit_empty:
                        spec["podSelector"]["matchExpressions"] = []
                        key = "from" if direction == "Ingress" else "to"
                        spec[direction.lower()][0][key][0]["podSelector"]["matchExpressions"] = []
                else:
                    direction = "baseline"
                results[direction] = evaluate_network_policy(obj, params)["allowed"]
                if direction == "Egress" and wanted:
                    for endpoint in ("local", "peer"):
                        qualified = deepcopy(obj)
                        local = qualified["spec"]["podSelector"]
                        peer = qualified["spec"]["egress"][0]["to"][0]["podSelector"]
                        selector = local if endpoint == "local" else peer
                        selector["matchExpressions"] = [{"key": "extra", "operator": "Exists"}]
                        assert evaluate_network_policy(qualified, params)["allowed"] is False
            assert results == {"Ingress": wanted, "Egress": wanted, "baseline": True}, (source, destination, target)


def test_checked_choice_changes_bound_parameters_and_preflight(releases, monkeypatch):
    assert len({resource["spec"]["digest"] for _, resource in releases}) == 2
    for target, resource in releases:
        spec = resource["spec"]
        assert spec["flows"] == [{"source": "git", "destination": "db-git", "port": 5432},
                                 {"source": "idp", "destination": target, "port": 5432}]
        policy = render_policy(rule="in-zone-flow", digest=spec["digest"])
        binding = render_binding(rule="in-zone-flow", digest=spec["digest"], parameter_name="database")
        assert policy["metadata"]["name"] == binding["spec"]["policyName"]
        assert binding["spec"]["paramRef"] == {"name": resource["metadata"]["name"],
                                               "parameterNotFoundAction": "Deny"}
        assert any(v["expression"] == f"params.spec.digest == '{spec['digest']}'"
                   for v in policy["spec"]["validations"])
    check_grants(releases, monkeypatch, explicit_empty=False)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Read decisions/admission-database-selector.md. Make k8s-admission/managed_network_policy.py "
    "admit the same exact service selector when matchExpressions is an empty list."))
def test_checked_choice_with_empty_selector_expressions(releases, monkeypatch):
    check_grants(releases, monkeypatch, explicit_empty=True)
