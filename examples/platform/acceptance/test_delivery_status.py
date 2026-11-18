import pytest

from query_fixture import portal_template


def test_delivery_status():
    render = portal_template("delivery_status").render
    sha = "ad" * 20
    for team, delivery, step, state, event in (
            ("elm", "elm-1", "identity", "pending", "2026-01-01T10:00:00Z"),
            ("reed", "reed-1", "identity", "success", "2026-01-01T10:01:00Z"),
            ("elm", "elm-1", "database", "failure", "2026-01-01T10:03:00Z")):
        observed = dict(sha=sha, tenant=team, delivery=delivery, step=step, state=state, eventTime=event)
        assert render(observed) == {"sha": sha, "context": f"rezono/delivery/{team}/{delivery}/{step}",
                                    "state": state, "eventTime": event}
