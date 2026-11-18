"""Read the latest matching provider status across pages."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/delivery-commit-status.md. Implement loop/forgejo_read.py. Read the latest matching provider status across pages.")
def test_forgejo_read(monkeypatch):
    read_status = entry(monkeypatch, "forgejo_read", "read_status")
    sha = "ab" * 20
    context = "rezono/delivery/elm/elm-1/seed"
    calls = []
    def request(method, path, *, query):
        assert (method, path) == ("GET", f"/api/v1/repos/example/delivery/commits/{sha}/statuses")
        calls.append(query)
        return {1: [{"context": "other"}, {"context": "another"}],
                2: [{"context": context, "status": "success", "target_url": "https://example.org/rows/7"},
                    {"context": context, "status": "pending", "target_url": "https://example.org/rows/3"}]}[query["page"]]
    assert read_status(request, "example", "delivery", sha, context, page_size=2) == {
        "state": "success", "evidence": "https://example.org/rows/7"}
    assert calls == [{"page": 1, "limit": 2}, {"page": 2, "limit": 2}]
    def broken_read(*args, **kwargs):
        raise OSError("provider unavailable")
    with pytest.raises(OSError):
        read_status(broken_read, "example", "delivery", sha, context, page_size=2)
