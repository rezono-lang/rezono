"""The shared release fixture hands the admission probe the same isolated API."""

import os
from pathlib import Path

import pytest


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, reason="Read decisions/shared-disposable-cluster.md. Depends on test_cluster_live_identity, test_cluster_admission_application and admission's test_desired_admission_release_reuses_both_rule_renderers. Stage the fixture Git mirror, pinned Argo and its render plugin in loop/cluster/ and connect the identity and kubeconfig in the disposable workflow. The admission component owns the real API dry-run.")
def test_shared_admission_handoff():
    temp = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    shared = Path(os.environ["REZONO_CLUSTER_KUBECONFIG"]).resolve(strict=True)
    scoped = Path(os.environ["REZONO_ADMISSION_TEST_KUBECONFIG"]).resolve(strict=True)
    assert shared.is_relative_to(temp) and shared.samefile(scoped)
    assert os.environ["REZONO_ADMISSION_TEST_APPLICATION"] == "rezono-admission"
    assert os.environ["REZONO_ADMISSION_TEST_APPLICATION_NAMESPACE"] == "argocd"
    import json
    import subprocess

    cmd = ["kubectl", "--kubeconfig", str(shared), "--context", "kind-rezono-fixture",
           "--request-timeout=15s", "-n", "argocd", "get", "application.argoproj.io",
           "rezono-admission", "-o", "json"]
    app = json.loads(subprocess.check_output(cmd, text=True, timeout=20))
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                                       text=True, timeout=10).strip()
    assert app["spec"]["source"]["targetRevision"] == checkout
    assert app["status"]["sync"]["revision"] == checkout
    assert app["status"]["sync"]["status"] == "Synced"
