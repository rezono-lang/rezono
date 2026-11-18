"""The pinned engine stops the deployment and clears its storage asynchronously."""

from urllib.error import HTTPError

import feldera


def test_stop_allows_immediate_deletion(monkeypatch):
    path = "/v0/pipelines/example"
    state = {"deployment_status": "Running", "storage_status": "InUse"}

    observations = []

    def request(method, endpoint):
        if (method, endpoint) == ("POST", path + "/stop?force=true"):
            state["deployment_status"] = "Stopping"
        elif (method, endpoint) == ("GET", path):
            observations.append(state.copy())
            return state.copy()
        elif (method, endpoint) == ("POST", path + "/clear"):
            assert state["deployment_status"] == "Stopped"
            state["storage_status"] = "Clearing"
        elif (method, endpoint) == ("DELETE", path):
            if state["storage_status"] != "Cleared":
                raise HTTPError(path, 400, "DeleteRestrictedToClearedStorage", {}, None)
        else:
            raise AssertionError((method, endpoint))

    def advance(_):
        if state["deployment_status"] == "Stopping":
            state["deployment_status"] = "Stopped"
        else:
            assert state["storage_status"] == "Clearing"
            state["storage_status"] = "Cleared"

    monkeypatch.setattr(feldera, "call", request)
    monkeypatch.setattr(feldera.time, "sleep", advance)
    feldera.stop("example")
    feldera.call("DELETE", path)
    assert observations[-1] == {"deployment_status": "Stopped", "storage_status": "Cleared"}


def test_hosted_deploy_releases_the_previous_compiler_before_building(monkeypatch, tmp_path):
    import subprocess

    namespace = "feldera-oracle-123-1"
    service = namespace + "-engine"
    monkeypatch.setenv("FELDERA_ORACLE_SANDBOX", namespace)
    monkeypatch.setenv("FELDERA_ORACLE_IMAGE", "engine-by-digest")
    monkeypatch.setenv("FELDERA_ORACLE_INPUT_DIR", str(tmp_path))
    monkeypatch.setenv("FELDERA_ORACLE_REPORTS", str(tmp_path))
    monkeypatch.setenv("FELDERA_URL", "http://127.0.0.1:8080")
    events = []
    services = set()

    def command(args, **kwargs):
        if args[:3] == ["docker", "container", "inspect"]:
            assert args[3:] == [service]
            return subprocess.CompletedProcess(args, 0 if service in services else 1)
        if args[:2] == ["docker", "run"]:
            assert service not in services
            assert args[args.index("--network") + 1] == "container:" + namespace
            assert args[args.index("--name") + 1] == service
            assert "CARGO_NET_OFFLINE=true" in args and args[-1] == "engine-by-digest"
            assert any("dst=/tmp/rezono-oracle-input,readonly" in arg for arg in args)
            services.add(service)
            events.append("start")
        elif args[:2] == ["docker", "logs"]:
            assert args[-1] == service
        elif args[:2] == ["docker", "rm"]:
            assert "--volumes" in args and args[-1] == service
            services.remove(service)
            events.append("release")
        elif args[0] == "curl":
            assert args[-1] == "http://127.0.0.1:8080/healthz"
            events.append("ready")
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0)

    def request(method, path, body=None):
        if method == "PUT":
            events.append(("compile", body["program_code"]))

    monkeypatch.setattr(subprocess, "run", command)
    monkeypatch.setattr(feldera, "call", request)
    monkeypatch.setattr(feldera, "wait", lambda *args: None)
    feldera.deploy("one", "SELECT 1")
    feldera.deploy("two", "SELECT 2")
    assert events == ["start", "ready", ("compile", "SELECT 1"),
                      "release", "start", "ready", ("compile", "SELECT 2")]
