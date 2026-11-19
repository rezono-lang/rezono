"""Claim one nonrepeatable plan hash durably, as the Claim action of formal/Rounds.tla.

Claim(w, m) needs claims[m] = 0 and sets claims[m] = w. The claims map is never reset, so a plan hash has at
most one attempt (AtMostOneSubmitPerNonrepeatableHash). The archive's conditional put_new is the claims map:
the first write of the key wins, an identical write is a no-op, and a different write is refused.
"""

from collections.abc import Mapping
import json
import re


CLAIMS = "loop/attempt-claims"


def claim_attempt(archive, *, plan_hash: str, run: str, cut: str, worker: str) -> dict[str, str] | None:
    """Return the claim of plan_hash for worker at run and cut, or None when the hash is claimed otherwise."""
    if not isinstance(plan_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise ValueError("expected a lowercase SHA-256 plan digest")
    for name, value in (("run", run), ("cut", cut), ("worker", worker)):
        if not isinstance(value, str) or not value:
            raise ValueError(f"expected a nonempty {name}")

    claim = {"plan_hash": plan_hash, "run": run, "cut": cut, "worker": worker}
    key = f"{CLAIMS}/{plan_hash}.json"
    try:
        archive.put_new(key, _encode(claim))
    except Exception:
        held = _decode(archive.get(key), plan_hash)
        if held is None:
            raise
        return claim if held == claim else None
    return claim


def _encode(claim: Mapping[str, str]) -> bytes:
    return json.dumps(claim, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _decode(data: bytes | None, plan_hash: str) -> dict[str, str] | None:
    """Read back a retained claim of plan_hash; None when the key holds no such claim."""
    if data is None:
        return None
    try:
        held = json.loads(data)
    except ValueError:
        return None
    if (
        not isinstance(held, dict)
        or set(held) != {"plan_hash", "run", "cut", "worker"}
        or held["plan_hash"] != plan_hash
        or not all(isinstance(value, str) and value for value in held.values())
    ):
        return None
    return held
