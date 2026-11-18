"""Resolve only declared fixture cases and exact synthetic endpoints."""

from pathlib import Path
from runpy import run_path

import pytest


def test_case_scope():
    resolve_case = run_path(str(Path(__file__).resolve().parents[1] / "case_scope.py"))["resolve_case"]
    case = {"id": "echo-ok", "source": "sender", "destination": "echo", "protocol": "TCP", "port": 8080}
    inventory = {"sender", "echo", "spare"}
    assert resolve_case("echo-ok", [case], inventory) == case
    with pytest.raises(ValueError):
        resolve_case("unlisted", [case], inventory)
    with pytest.raises(ValueError):
        resolve_case("echo-ok", [{**case, "destination": "outside"}], inventory)
