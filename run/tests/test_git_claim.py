"""Shared write-once claim in a Git remote, from decisions/run-shared-claim.md."""

from concurrent.futures import ThreadPoolExecutor
import subprocess
from threading import Barrier

import pytest

from offline_cases import implementation, PLAN_HASH


def bare(path):
    subprocess.run(["git", "init", "--bare", "-q", str(path)], check=True)
    return str(path)


def git(remote, *args):
    return subprocess.run(["git", "--git-dir", remote, *args], check=True,
                          capture_output=True, text=True).stdout


def test_git_claim(tmp_path):
    claim = implementation("git_claim.py", "claim_once")
    holder = implementation("git_claim.py", "holder")
    remote = bare(tmp_path / "claims.git")
    start = Barrier(6)

    def attempt(index):
        start.wait(timeout=30)
        return claim(remote, PLAN_HASH, f"run-{index}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count(True) == 1 and results.count(False) == 5
    winner = f"run-{results.index(True)}"
    ref = f"refs/rezono/run-claims/{PLAN_HASH}"
    assert git(remote, "for-each-ref", "--format=%(refname)").split() == [ref]
    assert git(remote, "log", "-1", "--format=%B", ref).strip() == f"run-claim {PLAN_HASH} {winner}"
    assert holder(remote, PLAN_HASH) == winner

    fresh = implementation("git_claim.py", "claim_once")
    assert fresh(remote, PLAN_HASH, winner) is False
    assert holder(remote, "b" * 64) is None
    assert fresh(remote, "b" * 64, "run-9") is True
    assert holder(remote, "b" * 64) == "run-9"

    # Identical arguments give the identical claim commit in any remote.
    other = bare(tmp_path / "other.git")
    assert fresh(other, PLAN_HASH, winner) is True
    assert git(other, "rev-parse", ref) == git(remote, "rev-parse", ref)

    for plan_hash, run_id in (("bad-digest", "run-1"), (PLAN_HASH.upper(), "run-1"), ("c" * 64, "run 1"),
                              ("c" * 64, "")):
        with pytest.raises(ValueError):
            fresh(remote, plan_hash, run_id)
    # An unreachable remote is unknown, never a consumed claim.
    with pytest.raises(RuntimeError):
        fresh(str(tmp_path / "missing.git"), "c" * 64, "run-1")
    with pytest.raises(RuntimeError):
        holder(str(tmp_path / "missing.git"), "c" * 64)
