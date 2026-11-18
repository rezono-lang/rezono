"""Read the latest matching provider status across pages."""

import pytest

from wire_fixtures import entry


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


@pytest.mark.parametrize("change_repeated_row", [False, True])
def test_status_history_refuses_overlapping_pages(change_repeated_row):
    from loop.forgejo_read import read_status

    sha = "ab" * 20
    context = "rezono/delivery/elm/elm-1/seed"
    row = {"id": 1, "context": context, "status": "pending", "target_url": "https://example.org/rows/3"}
    def request(method, path, *, query):
        assert (method, path) == ("GET", f"/api/v1/repos/example/delivery/commits/{sha}/statuses")
        if query["page"] == 1 or not change_repeated_row:
            return [row]
        return [{**row, "status": "success"}]
    with pytest.raises(ValueError, match="did not advance|repeated provider ID"):
        read_status(request, "example", "delivery", sha, context, blocks_write=lambda _: False)
