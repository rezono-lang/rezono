"""Delete a released claim only with the ref lease, and record an uncertain answer as unknown."""
import subprocess
from importlib.util import find_spec

import pytest

T = 1_800_000_000
G = "c" * 40
PLAN = {"run": "current", "branch": "task/old", "generation": G}
DELETE = ["git", "push", f"--force-with-lease=refs/heads/task/old:{G}", "origin", ":refs/heads/task/old"]


class Runner:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if isinstance(self.answer, Exception):
            raise self.answer
        return subprocess.CompletedProcess(argv, self.answer[0], stdout="", stderr=self.answer[1])


def test_build_claim_delete():
    assert find_spec("loop.build_claim_delete") is not None, "The conditional claim delete adapter is missing"
    from loop.build_claim_delete import delete_claim

    def record(outcome):
        return {"id": f"task/old@{G}", "run": "current", "branch": "task/old", "generation": G, "sent_at": T,
                "outcome": outcome, "source": "claim-delete"}

    for answer, outcome in (
        ((0, ""), "sent"),
        ((1, " ! [rejected]        task/old (stale info)\n"), "refused"),
        ((1, " ! [remote rejected] task/old (deletion of the current branch prohibited)\n"), "refused"),
        ((128, "fatal: unable to access the remote\n"), "unknown"),
        (subprocess.TimeoutExpired(DELETE, 30), "unknown"),
    ):
        runner = Runner(answer)
        result = delete_claim(PLAN, recheck=lambda branch: "none", push=runner, clock=lambda: T, source="claim-delete")
        assert runner.calls == [DELETE], f"Expected exactly the conditional delete, got {runner.calls}"
        assert result == record(outcome), f"{answer!r} must be recorded as {outcome}: {result}"

    for recheck in ("open", None):
        runner = Runner((0, ""))
        result = delete_claim(PLAN, recheck=lambda branch, state=recheck: state, push=runner, clock=lambda: T,
                              source="claim-delete")
        assert (result, runner.calls) == (None, []), f"A {recheck} recheck must skip the delete"

    for plan in (dict(PLAN, generation="C" * 40), dict(PLAN, branch="main"), dict(PLAN, branch="task/../main")):
        runner = Runner((0, ""))
        with pytest.raises(ValueError):
            delete_claim(plan, recheck=lambda branch: "none", push=runner, clock=lambda: T, source="claim-delete")
        assert runner.calls == []
