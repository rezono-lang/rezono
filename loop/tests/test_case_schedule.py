"""Schedule each declared synthetic case exactly once without expanding host or port ranges."""

import pytest

from wire_fixtures import entry, fixture


def test_case_schedule(monkeypatch):
    schedule = entry(monkeypatch, "case_schedule", "schedule")
    cases = fixture("network")["cases"]
    expected = sorted((c["id"], c["source"], c["destination"], c["protocol"], c["port"]) for c in cases)
    assert list(schedule(cases)) == expected
    assert list(schedule(list(reversed(cases)))) == expected
    with pytest.raises(ValueError):
        list(schedule([*cases, cases[0]]))
