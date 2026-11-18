"""Bind Argo's synthetic admission fixture to an immutable checkout revision."""

import json
import os

import pytest

from cluster_scenarios import CLUSTER, command


def test_cluster_admission_application(tmp_path):
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


def test_cluster_admission_application_reads_its_source_profile(tmp_path):
    profile = tmp_path / "source.toml"
    repository = "https://mirror.example.org/fixture.git"
    plugin = "synthetic-admission-v2"
    profile.write_text(f'repository_url = "{repository}"\nplugin_name = "{plugin}"\n', encoding="utf-8")
    args = [CLUSTER / "admission_application.py", "--revision", "ca" * 20]
    default = command(args, tmp_path, os.environ.copy())
    result = command([*args, "--source-profile", profile], tmp_path, os.environ.copy())
    assert default.returncode == result.returncode == 0, result.stderr
    expected = json.loads(default.stdout)
    expected["spec"]["source"].update(repoURL=repository, plugin={"name": plugin})
    assert json.loads(result.stdout) == expected


@pytest.mark.parametrize(
    "profile_text",
    [
        'repository_url = "https://mirror.example.org/fixture.git"',
        'repository_url = "https://mirror.example.org/fixture.git"\nplugin_name = 42',
        'repository_url = "https://mirror.example.org/fixture.git"\nplugin_name = ""',
        'repository_url = "https://mirror.example.org/fixture.git"\nplugin_name = "contains spaces"',
        'repository_url = "file:///fixture.git"\nplugin_name = "plugin"',
        'repository_url = "https://mirror.example.org:abc/fixture.git"\nplugin_name = "plugin"',
        'repository_url = "https://name@mirror.example.org/fixture.git"\nplugin_name = "plugin"',
        'repository_url = "https://mirror.example.org/fixture.git?mode=alternate"\nplugin_name = "plugin"',
        'repository_url = "https://mirror.example.org/fixture.git"\nplugin_name = "plugin"\nrevision = "main"',
        'repository_url = "https://mirror.example.org/fixture.git"\nplugin_name = "plugin"\nplugin_name = "other"',
    ],
)
def test_cluster_admission_application_refuses_invalid_source_profile(tmp_path, profile_text):
    profile = tmp_path / "source.toml"
    profile.write_text(profile_text, encoding="utf-8")
    args = [CLUSTER / "admission_application.py", "--revision", "ca" * 20, "--source-profile", profile]
    result = command(args, tmp_path, os.environ.copy())
    assert result.returncode == 2
    assert not result.stdout
    assert "invalid source profile" in result.stderr
