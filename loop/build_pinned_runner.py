"""Read and validate the pinned earlier main commit used to run the build pack."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

import yaml

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _require_sha40(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA40.fullmatch(value):
        raise ValueError(f"{label} must be a 40-lowercase-hex commit SHA, got {value!r}")
    return value


def read_engine_pin(path: Path | str) -> str:
    """Read and validate ``engine_sha`` from ``build/engine-pin.yaml``."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid engine pin YAML in {path}") from exc
    if not isinstance(data, dict) or "engine_sha" not in data:
        raise ValueError(f"engine pin file {path} must be a mapping containing 'engine_sha'")
    return _require_sha40(data["engine_sha"], "engine_sha")


def _git_ok(root: Path, *args: str) -> bool:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def validate_engine_pin(
    *,
    root: Path | str,
    engine_sha: str,
    candidate_sha: str,
    main_ref: str = "refs/remotes/origin/main",
) -> dict[str, Any]:
    """Validate that ``engine_sha`` is an earlier main commit distinct from ``candidate_sha``.

    Raises ``ValueError`` if either SHA is malformed, if ``engine_sha == candidate_sha``,
    if ``main_ref`` is invalid, or if ``engine_sha`` is not an ancestor of ``main_ref``.
    """
    engine = _require_sha40(engine_sha, "engine_sha")
    candidate = _require_sha40(candidate_sha, "candidate_sha")
    if not isinstance(main_ref, str) or not main_ref.strip():
        raise ValueError(f"main_ref must be a non-empty Git ref, got {main_ref!r}")
    if engine == candidate:
        raise ValueError("pinned engine_sha must not equal candidate_sha")

    repo = Path(root)
    if not _git_ok(repo, "rev-parse", "--verify", f"{engine}^{{commit}}"):
        raise ValueError(f"engine_sha {engine} is not a commit in {repo}")
    if not _git_ok(repo, "rev-parse", "--verify", f"{main_ref}^{{commit}}"):
        raise ValueError(f"main_ref {main_ref!r} is not a commit in {repo}")
    if not _git_ok(repo, "merge-base", "--is-ancestor", engine, main_ref):
        raise ValueError(f"engine_sha {engine} is not an ancestor of {main_ref!r}")

    return {
        "engine_sha": engine,
        "candidate_sha": candidate,
        "main_ref": main_ref,
        "pinned": True,
    }
