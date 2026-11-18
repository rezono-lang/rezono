"""Address the status write to the supplied proposal commit."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/delivery-commit-status.md. Implement loop/forgejo_write.py. Address the status write to the supplied proposal commit.")
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
