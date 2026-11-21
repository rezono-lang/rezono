"""A valid login and a current right are independently required for a cluster read."""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import pytest

from case_support import verified


def records():
    return {
        "cluster_membership": [
            {"id": "elm-lease", "identity": "reader", "organization": "elm", "begins": "2026-06-01", "ends": "2026-06-10"},
            {"id": "reed-lease", "identity": "peer", "organization": "reed", "begins": "2026-06-01", "ends": "2026-06-30"}],
        "cluster_action_decision": [
            {"id": "elm-read", "organization": "elm", "tenant_role": "reader", "cluster": "elm-app", "action": "get",
             "resource": "configmaps", "namespace": "elm"},
            {"id": "reed-read", "organization": "reed", "tenant_role": "reader", "cluster": "reed-app", "action": "get",
             "resource": "configmaps", "namespace": "reed"}],
        "cluster_tenant_role": [
            {"id": "role-elm", "identity": "reader", "organization": "elm", "tenant_role": "reader"},
            {"id": "role-reed", "identity": "peer", "organization": "reed", "tenant_role": "reader"}],
        "cluster_emergency_grant": [{"id": "emergency-window", "identity": "operator", "cluster": "elm-app",
                                     "action": "get", "resource": "pods", "namespace": "elm",
                                     "begins": "2026-06-08", "ends": "2026-06-09"}],
        "cluster_right_clock": [{"id": "evaluation", "day": "2026-06-08"}],
    }


def test_management_cluster_rights():
    from management_probes import compiled

    data = records()
    elm = ("reader", "elm-app", "get", "configmaps", "elm")
    reed = ("peer", "reed-app", "get", "configmaps", "reed")
    emergency = ("operator", "elm-app", "get", "pods", "elm")
    for day, expected in (("2026-06-08", {elm, reed, emergency}), ("2026-06-09", {elm, reed}), ("2026-06-10", {reed})):
        data["cluster_right_clock"][0]["day"] = day
        model, state = compiled(data)
        assert state.derived.get("managed_cluster_right") == expected
        if elm in expected:
            leaves = verified("managed_cluster_right", elm, state=(model, state))
            for kind, identifier in (("cluster_membership", "elm-lease"), ("cluster_action_decision", "elm-read"),
                                     ("cluster_tenant_role", "role-elm")):
                assert any(rel.startswith(kind + "__") and key[0] == identifier for rel, key in leaves)


@pytest.mark.cluster
def test_management_membership_withdrawal():
    from management_probes import live_events

    events = live_events("access")
    before, denied = [e for e in events if e["kind"] == "same-credential-read"]
    assert (before["status"], denied["status"], denied["reason"]) == (200, 403, "Forbidden")
    for field in ("identity", "credential_ref", "expires_at", "cluster", "namespace", "resource", "verb"):
        assert before[field] == denied[field]
    assert denied["verb"] == "get" and denied["resource"] == "configmaps/public-marker"
    assert datetime.fromisoformat(denied["observed_at"]) < datetime.fromisoformat(denied["expires_at"])
    applied, = [e for e in events if e["kind"] == "binding-applied"]
    withdrawn, = [e for e in events if e["kind"] == "right-withdrawn"]
    absent, = [e for e in events if e["kind"] == "binding-read-absent"]
    assert events.index(applied) < events.index(before) < events.index(withdrawn) < events.index(absent) < events.index(denied)
    assert withdrawn["weight"] == -1 and withdrawn["source_manifest"] == applied["publication_sha256"]
    assert len(withdrawn["source_manifest"]) == 64 and withdrawn["previous_right_witness"] and withdrawn["membership"] == "elm-lease"
    assert applied["binding_uid"] == absent["previous_binding_uid"] and absent["complete"] is True
    assert (withdrawn["identity"], withdrawn["cluster"], withdrawn["namespace"]) == (before["identity"], before["cluster"], before["namespace"])
    crossing, = [e for e in events if e["kind"] == "other-tenant-read"]
    assert crossing["status"] == 403 and crossing["identity"] == before["identity"] and crossing["cluster"] != before["cluster"]

    # Repeat the ordinary read as the fixture tenant. A credential that still authenticates must receive Forbidden.
    config = Path(os.environ["REZONO_TENANT_TEST_KUBECONFIG"]).resolve(strict=True)
    assert config.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True))
    command = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
    assert subprocess.check_output([*command, "config", "current-context"], text=True).strip() == "kind-rezono-fixture-tenant"
    server = subprocess.check_output([*command, "config", "view", "--minify", "-o",
                                      "jsonpath={.clusters[0].cluster.server}"], text=True)
    target = urlparse(server)
    assert target.scheme == "https" and target.hostname in {"localhost", "127.0.0.1", "::1"}
    who = json.loads(subprocess.check_output([*command, "auth", "whoami", "-o", "json"], text=True, timeout=20))
    assert who["status"]["userInfo"]["username"] == denied["identity"]
    assert denied["namespace"] == "elm"
    result = subprocess.run([*command, "-n", "elm", "get", "configmap", "public-marker", "-o", "name"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and "(Forbidden)" in result.stderr
