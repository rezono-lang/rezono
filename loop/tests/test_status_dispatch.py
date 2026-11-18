"""Compose the accepted proposal and observations into provider traffic."""

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
        body = options["body"]
        sent.append({**body, "status": body["state"]})

    for records in (observations, list(reversed(observations))):
        report_step(request, "example", "delivery", {"commit": sha, "accepted": True}, step, records,
                    publish_evidence=publish_evidence)
    assert stored[0] == stored[1]
    assert len(sent) == 1
    assert sent[0]["status"] == "success"
    assert sent[0]["target_url"].endswith(stored[0].proofs[0]["manifest_id"])


class CommitStatuses:
    """Keep the documented provider fields across independent client calls."""

    def __init__(self):
        self.rows = {}

    def client(self):
        def request(method, path, **options):
            endpoint, sha = path.rsplit("/", 1)
            if method == "GET":
                repository, resource, sha = endpoint.rsplit("/", 2)
                assert resource == "commits"
                rows = self.rows.get((repository, sha), [])
                page, limit = options["query"]["page"], options["query"]["limit"]
                return list(reversed(rows))[(page - 1) * limit:page * limit]
            assert method == "POST"
            repository, resource = endpoint.rsplit("/", 1)
            assert resource == "statuses"
            body = options["body"]
            row = {**body, "status": body["state"]}
            self.rows.setdefault((repository, sha), []).append(row)
            return row

        return request

    def published(self, sha):
        return [(row["status"], row["target_url"])
                for row in self.rows.get(("/api/v1/repos/example/delivery", sha), [])]


def dated_observations():
    step = {"run": "r", "tenant": "elm", "delivery": "elm-1", "step": "seed"}
    done = {**step, "id": "done", "relation": "done", "reason": "https://example.org/done",
            "at": "2026-01-01T00:02:00Z"}
    stuck = {**step, "id": "stuck", "relation": "stuck", "reason": "https://example.org/stuck",
             "at": "2026-01-01T00:01:00Z"}
    return step, done, stuck


def test_delayed_status_cannot_replace_newer_evidence():
    from loop.status_dispatch import report_step

    sha = "ac" * 20
    proposal = {"commit": sha, "accepted": True}
    step, done, stuck = dated_observations()
    provider = CommitStatuses()
    report_step(provider.client(), "example", "delivery", proposal, step, [done])
    report_step(provider.client(), "example", "delivery", proposal, step, [stuck])
    assert [state for state, _ in provider.published(sha)] == ["success"]


def test_status_uses_the_grounded_instant_and_keeps_other_runs_independent():
    from loop.status_dispatch import report_step

    sha = "ac" * 20
    proposal = {"commit": sha, "accepted": True}
    step, done, stuck = dated_observations()
    provider = CommitStatuses()
    not_grounded = {**done, "id": "applied", "relation": "applied", "at": "2026-01-03T00:00:00Z"}
    report_step(provider.client(), "example", "delivery", proposal, step, [done, not_grounded])
    report_step(provider.client(), "example", "delivery", proposal, step,
                [{**done, "at": "2026-01-01T01:02:00+01:00"}])
    assert [state for state, _ in provider.published(sha)] == ["success"]

    report_step(provider.client(), "example", "delivery", proposal, step, [{**stuck, "at": "2026-01-01T00:03:00Z"}])
    other_run = {**step, "run": "another"}
    report_step(provider.client(), "example", "delivery", proposal, other_run, [{**done, **other_run}])
    assert [state for state, _ in provider.published(sha)] == ["success", "failure", "success"]


def test_separate_reports_for_the_same_instant_require_complete_conflict_evidence():
    from loop.status_dispatch import report_step

    sha = "ac" * 20
    proposal = {"commit": sha, "accepted": True}
    step, done, stuck = dated_observations()
    stuck = {**stuck, "at": "2026-01-01T01:02:00+01:00"}
    provider = CommitStatuses()
    proof_url = "https://example.org/status-evidence/complete"

    report_step(provider.client(), "example", "delivery", proposal, step, [done])
    report_step(provider.client(), "example", "delivery", proposal, step, [stuck],
                publish_evidence=lambda _: stuck["reason"])
    assert provider.published(sha) == [("success", done["reason"])]

    # Two agreeing waiting sources contain no evidence of the previous completion.
    waiting = [{**row, "relation": "waiting"} for row in (done, stuck)]
    report_step(provider.client(), "example", "delivery", proposal, step, waiting,
                publish_evidence=lambda _: "https://example.org/status-evidence/waiting")
    unrelated = {**done, "reason": "https://example.org/unrelated"}
    report_step(provider.client(), "example", "delivery", proposal, step, [unrelated, stuck],
                publish_evidence=lambda _: "https://example.org/status-evidence/unrelated")
    assert provider.published(sha) == [("success", done["reason"])]

    def publish_evidence(projection):
        assert projection.reasons == {done["reason"], stuck["reason"]}
        assert len(projection.proofs) == 2
        return proof_url

    report_step(provider.client(), "example", "delivery", proposal, step, [done, stuck],
                publish_evidence=publish_evidence)
    report_step(provider.client(), "example", "delivery", proposal, step, [done])
    assert provider.published(sha) == [("success", done["reason"]), ("pending", proof_url)]


def test_conflicting_status_requires_a_link_to_the_complete_proof():
    from loop.status_dispatch import report_step

    sha = "ac" * 20
    proposal = {"commit": sha, "accepted": True}
    step, done, stuck = dated_observations()
    provider = CommitStatuses()
    conflicting = [done, {**stuck, "at": done["at"]}]
    report_step(provider.client(), "example", "delivery", proposal, step, conflicting)
    assert provider.published(sha) == []

    proof_url = "https://example.org/status-evidence/complete"

    def publish_evidence(projection):
        assert projection.reasons == {done["reason"], stuck["reason"]}
        assert {row["id"] for row in projection.observations} == {done["id"], stuck["id"]}
        assert len(projection.proofs) == 2
        return proof_url

    report_step(provider.client(), "example", "delivery", proposal, step, conflicting,
                publish_evidence=publish_evidence)
    assert provider.published(sha) == [("pending", proof_url)]
