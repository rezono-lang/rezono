"""Turn a task ref listing and its push activity into dated claim observations."""
from __future__ import annotations

import re
from datetime import UTC, datetime

_PREFIX = "refs/heads/task/"
_SHA = re.compile(r"[0-9a-f]{40}")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
    elapsed = moment - _EPOCH
    if elapsed.microseconds:
        raise ValueError("push timestamp is not a whole second")
    return elapsed.days * 86400 + elapsed.seconds


def claim_rows(refs, activity, *, run, observed_at, source, activity_source):
    """Return the BuildClaim and BuildClaimActivity rows for the task refs.

    Every push record of a listed claim becomes a BuildClaimActivity row with ``activity_source``,
    the origin of the activity answer. The adapter does not choose the latest push; the rules do.
    """
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
        candidates = {
            (_unix(record["timestamp"]), _sha(record["after"], f"push to {name}"))
            for record in activity.get(name, ())
        }
        for pushed_at, after in sorted(candidates):
            pushes.append({"id": f"{claim}@{after}@{pushed_at}", "claim": claim, "after": after,
                           "pushed_at": pushed_at, "source": activity_source})
    return {"build_claim": claims, "build_claim_activity": pushes}
