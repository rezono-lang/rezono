"""Select the immutable commit for an accepted delivery proposal."""

import re
from collections.abc import Mapping


def target(proposal: Mapping[str, object]) -> str | None:
    """Return the accepted proposal's pinned commit for status publication."""
    if proposal.get("accepted") is not True:
        return None

    commit = proposal.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("accepted proposal requires a full lowercase Git commit object ID")
    return commit
