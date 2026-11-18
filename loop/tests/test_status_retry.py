"""Read the latest logical status before each retry."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.mark.xfail(strict=True, reason="Read decisions/delivery-commit-status.md. Implement loop/status_retry.py. Read the latest logical status before each retry.")
def test_status_retry():
    publish = run_path(str(Path(__file__).resolve().parents[1] / "status_retry.py"))["publish"]
    remote = {}
    writes = []
    key = ("a" * 40, "rezono/delivery/elm/elm-1/database")
    def write(key, value):
        writes.append((key, value))
        remote[key] = value
        if len(writes) == 1:
            raise TimeoutError("response lost after storage")
    value = {"state": "success", "evidence": "observed-7"}
    with pytest.raises(TimeoutError):
        publish(key, value, remote.get, write)
    publish(key, value, remote.get, write)
    assert writes == [(key, value)]
    updated = {"state": "failure", "evidence": "observed-8"}
    publish(key, updated, remote.get, write)
    assert writes == [(key, value), (key, updated)]
