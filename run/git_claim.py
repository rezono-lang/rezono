"""Shared write-once claim in a Git remote, from decisions/run-shared-claim.md."""

import os
import re
import subprocess
import tempfile
import time

_HASH = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(r"[A-Za-z0-9._-]+")
_MESSAGE = re.compile(r"run-claim ([0-9a-f]{64}) ([A-Za-z0-9._-]+)")
_ATTEMPTS = 8


def _ref(plan_hash):
    return f"refs/rezono/run-claims/{plan_hash}"


def _check(plan_hash, run_id=None):
    if not isinstance(plan_hash, str) or not _HASH.fullmatch(plan_hash):
        raise ValueError("plan_hash must be 64 lowercase hexadecimal characters")
    if run_id is not None and (not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id)):
        raise ValueError("run_id must use letters, digits, '.', '_' and '-'")


def _git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)


def _remote_sha(scratch, remote, ref):
    """Return the commit the remote reference holds, or None when it is absent."""
    result = _git(scratch, "ls-remote", remote, ref)
    if result.returncode != 0:
        raise RuntimeError(f"cannot read claim remote: {result.stderr.strip()}")
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name == ref:
            return sha
    return None


def claim_once(remote, plan_hash, run_id):
    _check(plan_hash, run_id)
    ref = _ref(plan_hash)
    env = dict(os.environ)
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "rezono-run"
        env[f"GIT_{role}_EMAIL"] = "run@example.org"
        env[f"GIT_{role}_DATE"] = "@0 +0000"
    with tempfile.TemporaryDirectory() as scratch:
        if _git(scratch, "init", "--bare", "-q", ".").returncode != 0:
            raise RuntimeError("cannot create scratch repository")
        tree = _git(scratch, "hash-object", "-t", "tree", "-w", "--stdin", env=env)
        commit = _git(scratch, "commit-tree", tree.stdout.strip(), "-m",
                      f"run-claim {plan_hash} {run_id}", env=env)
        if tree.returncode != 0 or commit.returncode != 0:
            raise RuntimeError("cannot create claim commit")
        sha = commit.stdout.strip()
        for attempt in range(_ATTEMPTS):
            push = _git(scratch, "push", "--porcelain", f"--force-with-lease={ref}:", remote,
                        f"{sha}:{ref}", env=env)
            if push.returncode == 0:
                return any(line.startswith("*\t") for line in push.stdout.splitlines())
            # A lost race on the reference lock can fail before the winner is visible.
            if _remote_sha(scratch, remote, ref) is not None:
                return False
            if attempt + 1 < _ATTEMPTS:
                time.sleep(0.05 * (attempt + 1))
        raise RuntimeError(f"claim push failed: {push.stderr.strip()}")


def holder(remote, plan_hash):
    _check(plan_hash)
    ref = _ref(plan_hash)
    with tempfile.TemporaryDirectory() as scratch:
        if _git(scratch, "init", "--bare", "-q", ".").returncode != 0:
            raise RuntimeError("cannot create scratch repository")
        sha = _remote_sha(scratch, remote, ref)
        if sha is None:
            return None
        fetched = _git(scratch, "fetch", "-q", remote, ref)
        if fetched.returncode != 0:
            raise RuntimeError(f"cannot read claim: {fetched.stderr.strip()}")
        message = _git(scratch, "log", "-1", "--format=%B", sha)
        match = _MESSAGE.fullmatch(message.stdout.strip()) if message.returncode == 0 else None
        if not match or match.group(1) != plan_hash:
            raise RuntimeError("claim message has an unexpected form")
        return match.group(2)
