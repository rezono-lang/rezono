"""Select the immutable commit for an accepted delivery proposal."""

import re
from collections.abc import Mapping
from typing import TypeGuard


def is_commit_sha(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def target(proposal: Mapping[str, object]) -> str | None:
    """Return the accepted proposal's pinned commit for status publication."""
    if proposal.get("accepted") is not True:
        return None

    commit = proposal.get("commit")
    if not is_commit_sha(commit):
        raise ValueError("accepted proposal requires a full lowercase Git commit object ID")
    return commit
