"""Delete one released task claim with a ref lease, and record an uncertain answer as unknown."""

import re
import subprocess
from collections.abc import Callable, Mapping, Sequence

_SHA = re.compile(r"[0-9a-f]{40}")
_PREFIX = "task/"
_FORBIDDEN = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
_REFUSED = ("[rejected]", "[remote rejected]", "stale info")


def _branch(value: object) -> str:
    """Return the branch when it is a well-formed task claim branch."""
    if not isinstance(value, str) or not value.startswith(_PREFIX) or len(value) == len(_PREFIX):
        raise ValueError("branch is not a task claim branch")
    if _FORBIDDEN.search(value) or ".." in value or "@{" in value or value.endswith((".", "/", ".lock")):
        raise ValueError(f"branch {value!r} is not a valid ref name")
    if any(not part or part.startswith(".") or part.endswith(".lock") for part in value.split("/")):
        raise ValueError(f"branch {value!r} is not a valid ref name")
    return value


def _generation(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("generation is not a full lowercase commit ID")
    return value


def _outcome(push: Callable[[Sequence[str]], subprocess.CompletedProcess], argv: list[str]) -> str:
    """Return ``sent``, ``refused`` or ``unknown`` for one conditional delete."""
    try:
        answer = push(argv)
    except (subprocess.SubprocessError, OSError):
        return "unknown"
    if answer.returncode == 0:
        return "sent"
    stderr = answer.stderr if isinstance(answer.stderr, str) else ""
    if any(marker in stderr for marker in _REFUSED):
        return "refused"
    return "unknown"


def delete_claim(
    plan: Mapping[str, object],
    *,
    recheck: Callable[[str], str | None],
    push: Callable[[Sequence[str]], subprocess.CompletedProcess],
    clock: Callable[[], int],
    source: str,
) -> dict[str, object] | None:
    """Run the one conditional delete of a planned claim release and return its BuildClaimDelete record.

    ``recheck(branch)`` reads the pull requests for the branch immediately before the delete and
    returns ``"open"``, ``"none"`` or None when the answer is unreadable. Only ``"none"`` lets the
    delete run; otherwise nothing is sent and nothing is recorded. ``push(argv)`` runs the Git
    command and returns its completed process; a raised timeout or error records ``unknown``.
    """
    run = plan.get("run")
    if not isinstance(run, str) or not run.strip():
        raise ValueError("plan has no run")
    branch = _branch(plan.get("branch"))
    generation = _generation(plan.get("generation"))
    if recheck(branch) != "none":
        return None
    sent_at = clock()
    if type(sent_at) is not int:
        raise ValueError("clock did not give integer Unix seconds")
    argv = ["git", "push", f"--force-with-lease=refs/heads/{branch}:{generation}", "origin", f":refs/heads/{branch}"]
    return {
        "id": f"{branch}@{generation}",
        "run": run,
        "branch": branch,
        "generation": generation,
        "sent_at": sent_at,
        "outcome": _outcome(push, argv),
        "source": source,
    }
