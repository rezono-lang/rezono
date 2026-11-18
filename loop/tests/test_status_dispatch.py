"""Compose the accepted proposal and observations into provider traffic."""

import pytest

from wire_fixtures import entry


def test_status_dispatch(monkeypatch):
    report_step = entry(monkeypatch, "status_dispatch", "report_step")
    sha = "ac" * 20
    step = {"run": "r", "tenant": "elm", "delivery": "elm-1", "step": "seed"}
    evidence = "https://example.org/rows/22"
    obs = [{**step, "relation": "done", "reason": evidence}]
    statuses = []
    def request(method, path, **options):
        if method == "GET":
            assert path == f"/api/v1/repos/example/delivery/commits/{sha}/statuses"
            return list(reversed(statuses))
        assert (method, path) == ("POST", f"/api/v1/repos/example/delivery/statuses/{sha}")
        body = options["body"]
        statuses.append({"context": body["context"], "status": body["state"], "target_url": body["target_url"]})
        return {"id": len(statuses)}
    for accepted in (False, True, True):
        report_step(request, "example", "delivery", {"commit": sha, "accepted": accepted}, step, obs)
        if not accepted:
            assert statuses == []
    assert statuses == [{"context": "rezono/delivery/elm/elm-1/seed", "status": "success", "target_url": evidence}]
