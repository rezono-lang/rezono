"""Bind Argo's synthetic admission fixture to an immutable checkout revision."""

import json

import pytest

from cluster_scenarios import CLUSTER, command


def test_cluster_admission_application(tmp_path):
    import os

    path = CLUSTER / "admission_application.py"
    for sha in ["12" * 20, "ca" * 20]:
        response = command([path, "--revision", sha], tmp_path, os.environ.copy())
        assert response.returncode == 0, response.stderr
        app = json.loads(response.stdout)
        assert (app["apiVersion"], app["kind"]) == ("argoproj.io/v1alpha1", "Application")
        assert app["metadata"]["name"] == "rezono-admission" and app["metadata"]["namespace"] == "argocd"
        source = app["spec"]["source"]
        assert source["targetRevision"] == sha and source["path"] == "k8s-admission"
        assert source["plugin"]["name"] == "rezono-admission-fixture"
        assert source["repoURL"] == "http://fixture-git.fixture-system.svc/rezono.git"
        assert app["spec"]["destination"]["server"] == "https://kubernetes.default.svc"
        assert app["spec"]["syncPolicy"]["automated"] is not None
    assert command([path, "--revision", "main"], tmp_path, os.environ.copy()).returncode != 0
