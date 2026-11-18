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


def test_status_dispatch_links_the_published_rule_evidence():
    from loop.status_dispatch import report_step

    sha = "ac" * 20
    step = {"run": "r", "tenant": "elm", "delivery": "elm-1", "step": "seed"}
    observations = [
        {**step, "id": "old", "relation": "stuck", "at": "2026-01-01T00:00:00Z",
         "reason": "https://example.org/expired"},
        {**step, "id": "new", "relation": "done", "at": "2026-01-01T00:01:00Z",
         "reason": "https://example.org/completed"},
    ]
    stored, sent = [], []

    def publish_evidence(projection):
        stored.append(projection)
        assert projection.reasons == {"https://example.org/completed"}
        assert {r["id"] for r in projection.observations} == {"old", "new"}
        proof, = projection.proofs
        assert proof["root"]["relation"] == "current_delivery_status"
        return "https://example.org/status-evidence/" + proof["manifest_id"]

    def request(method, path, **options):
        if method == "GET":
            return sent
        sent.append({"status": options["body"]["state"], "target_url": options["body"]["target_url"],
                     "context": options["body"]["context"]})

    for records in (observations, list(reversed(observations))):
        report_step(request, "example", "delivery", {"commit": sha, "accepted": True}, step, records,
                    publish_evidence=publish_evidence)
    assert stored[0] == stored[1]
    assert len(sent) == 1
    assert sent[0]["status"] == "success"
    assert sent[0]["target_url"].endswith(stored[0].proofs[0]["manifest_id"])
