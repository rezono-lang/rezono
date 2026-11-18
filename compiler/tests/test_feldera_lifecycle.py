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
