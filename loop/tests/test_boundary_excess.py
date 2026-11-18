"""Preserve a residual allowance even when service isolation denies the same tuple."""

import pytest

from wire_fixtures import entry, fixture


def test_boundary_excess(monkeypatch):
    excess = entry(monkeypatch, "boundary_excess", "excess")
    cases = fixture("network")["cases"]
    assert excess(cases) == {"overlap"}
    assert excess([dict(c, router="deny") if c["id"] == "overlap" else c for c in cases]) == set()
