"""Address the status write to the supplied proposal commit."""

import pytest

from wire_fixtures import entry


def test_forgejo_write(monkeypatch):
    write_status = entry(monkeypatch, "forgejo_write", "write_status")
    sha = "ba" * 20
    context = "rezono/delivery/reed/reed-2/prepare"
    evidence = "https://example.org/rows/19"
    calls = []
    def request(method, path, *, body):
        calls.append((method, path, body))
        return {"id": 419}
    write_status(request, "example", "delivery", sha, context, {"state": "failure", "evidence": evidence})
    assert calls == [("POST", f"/api/v1/repos/example/delivery/statuses/{sha}",
                      {"context": context, "state": "failure", "target_url": evidence})]


@pytest.mark.parametrize("sha", ["main", "", None, "a" * 7, "g" * 40, "A" * 40])
def test_write_rejects_an_unpinned_commit(monkeypatch, sha):
    write_status = entry(monkeypatch, "forgejo_write", "write_status")

    def unexpected_request(*args, **kwargs):
        pytest.fail("the transport received a status for an unpinned commit")

    with pytest.raises(ValueError, match="full SHA"):
        write_status(unexpected_request, "example", "delivery", sha, "context",
                     {"state": "pending", "evidence": "row-1"})
