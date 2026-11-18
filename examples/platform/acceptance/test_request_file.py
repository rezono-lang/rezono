import json

import pytest

from query_fixture import portal_template


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Render a normalized tenant request to its versioned request-file path without changing its contents. Read decisions/platform-query-results.md. Write examples/platform/portal/request_file.py.")
def test_request_file():
    render = portal_template("request_file").render
    for team, service, profile in (("elm", "ledger", "production"), ("reed", "studio", "development")):
        request = {"submittedAt": "2026-01-01T00:00:00Z", "profile": profile,
                   "items": {"cluster": "small"}, "connections": []}
        path, body = render(team, service, request)
        assert path == f"teams/{team}/{service}/request.json"
        assert json.loads(body) == request
        assert render(team, service, request) == (path, body)
