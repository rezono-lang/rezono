"""The pinned engine stops the deployment and clears its storage asynchronously."""

import io
import json
from urllib.error import HTTPError, URLError

import pytest

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


def refusal(code, error_code, retry_after=None):
    body = io.BytesIO(json.dumps({"error_code": error_code}).encode())
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return HTTPError("http://localhost/ingress", code, error_code, headers, body)


def test_ingress_drains_each_accepted_chunk_and_obeys_explicit_refusal(monkeypatch):
    events = []
    attempts = 0

    def request(method, path, body=None):
        nonlocal attempts
        if method == "GET":
            events.append(("complete", path.rsplit("=", 1)[1]))
            return {"status": "complete"}
        attempts += 1
        row = json.loads(body)[0]
        if attempts == 2:
            events.append(("refused", row))
            raise refusal(429, "ApiConnectionLimit", "3")
        events.append(("accepted", row))
        return {"token": str(attempts)}

    monkeypatch.setattr(feldera, "call", request)
    monkeypatch.setattr(feldera.time, "sleep", lambda delay: events.append(("wait", delay)))
    add, remove = {"insert": {"id": "one"}}, {"delete": {"id": "one"}}
    feldera.processed("part", feldera.ingress_tokens("part", {"amount": [add, remove]}, chunk=1))
    assert events == [
        ("accepted", add), ("complete", "1"), ("refused", remove), ("wait", 3),
        ("accepted", remove), ("complete", "3"),
    ]


@pytest.mark.parametrize("error", [
    refusal(429, "AnotherLimit"), refusal(429, "ApiConnectionLimit", "180"),
    refusal(429, "ApiConnectionLimit", "unreadable"), refusal(503, "ApiConnectionLimit"),
    URLError("response lost"),
])
def test_unknown_write_outcome_and_excessive_delay_do_not_resubmit(monkeypatch, error):
    calls = []

    def fail(*args):
        calls.append(args)
        raise error

    monkeypatch.setattr(feldera, "call", fail)
    monkeypatch.setattr(feldera.time, "sleep", lambda _: pytest.fail("unexpected retry"))
    with pytest.raises(type(error)):
        feldera.push("part", {"amount": [{"insert": {"id": "one"}}]})
    assert len(calls) == 1


def test_persistent_connection_refusal_expires(monkeypatch):
    elapsed = 0
    attempts = 0

    def reject(*args):
        nonlocal attempts
        attempts += 1
        raise refusal(429, "ApiConnectionLimit")

    def advance(duration):
        nonlocal elapsed
        elapsed += duration

    monkeypatch.setattr(feldera, "call", reject)
    monkeypatch.setattr(feldera.time, "sleep", advance)
    monkeypatch.setattr(feldera.time, "monotonic", lambda: elapsed)
    with pytest.raises(HTTPError, match="429"):
        feldera.push("part", {"amount": [{"delete": {"id": "one"}}]})
    assert attempts > 1 and 0 < elapsed < 120
