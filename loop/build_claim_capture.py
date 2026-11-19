"""Turn a task ref listing and its push activity into dated claim observations."""
from __future__ import annotations

import re
from datetime import datetime

_PREFIX = "refs/heads/task/"
_SHA = re.compile(r"[0-9a-f]{40}")


def _sha(value: object, what: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError(f"{what} is not a full lowercase commit ID")
    return value


def _unix(timestamp: object) -> int:
    if not isinstance(timestamp, str):
        raise ValueError("push timestamp is not a string")
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise ValueError("push timestamp is not ISO 8601") from error
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("push timestamp has no UTC offset")
    return int(moment.timestamp())


def claim_rows(refs, activity, *, run, observed_at, source):
    """Return the BuildClaim and BuildClaimActivity rows for the task refs."""
    generations: dict[str, str] = {}
    for entry in refs:
        name = entry["ref"]
        if not name.startswith(_PREFIX) or len(name) == len(_PREFIX):
            continue
        if name in generations:
            raise ValueError(f"duplicate ref {name}")
        generations[name] = _sha(entry["object"]["sha"], f"generation of {name}")

    claims, pushes = [], []
    for name in sorted(generations):
        claim = name[len("refs/heads/"):]
        claims.append({"id": claim, "run": run, "branch": claim, "generation": generations[name],
                       "observed_at": observed_at, "source": source})
        newest = None
        for record in activity.get(name, ()):
            candidate = (_unix(record["timestamp"]), _sha(record["after"], f"push to {name}"))
            if newest is None or candidate > newest:
                newest = candidate
        if newest is not None:
            pushed_at, after = newest
            pushes.append({"id": f"{claim}@{after}", "claim": claim, "after": after,
                           "pushed_at": pushed_at, "source": source})
    return {"build_claim": claims, "build_claim_activity": pushes}
