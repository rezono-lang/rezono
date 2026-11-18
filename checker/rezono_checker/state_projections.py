"""Authenticate state projections against the epoch's independently archived Values."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from rezono_canon import sha256_hex

from .canon import encode_key


FILE = "ir/state-projections.json"
DESCRIPTOR_NAMES = ("relation", "source_relation", "value_column", "origin_column")
Values = Mapping[str, Mapping[str, object]]
Rows = Mapping[str, tuple[tuple[str, ...], Values]]


@dataclass(frozen=True)
class Projection:
    relation: str
    source_relation: str
    value_column: str
    origin_column: str


def _projections(data: bytes) -> list[Projection]:
    descriptors = json.loads(data)
    if not isinstance(descriptors, list):
        raise ValueError("state projections must be a list")
    projections = []
    for descriptor in descriptors:
        if (not isinstance(descriptor, dict) or set(descriptor) != {*DESCRIPTOR_NAMES, "required"}
                or not all(isinstance(descriptor[name], str) and descriptor[name] for name in DESCRIPTOR_NAMES)
                or type(descriptor["required"]) is not bool
                or descriptor["origin_column"] == descriptor["value_column"]):
            raise ValueError("invalid state projection descriptor")
        projections.append(Projection(*(descriptor[name] for name in DESCRIPTOR_NAMES)))
    targets = {p.relation for p in projections}
    if len(targets) != len(projections) or any(p.source_relation in targets for p in projections):
        raise ValueError("each state projection needs its own relation and an independent source")
    return projections


def _origin(value: Mapping[str, object]) -> str | None:
    text = value.get("value")
    return text if value.get("state") == "known" and isinstance(text, str) and text else None


def _matches(projection: Projection, parts: tuple[str, ...], values: Values, source: Rows) -> bool:
    if len(parts) != 3:
        return False
    subject, state, reason = parts
    row = source.get(encode_key((subject,)))
    if row is None:
        return False
    _, original = row
    value = original.get(projection.value_column)
    origin = _origin(original.get(projection.origin_column, {}))
    # A descriptor's required flag cannot turn an omitted Value into evidence of a state.
    return (value is not None and value["state"] == state and value.get("reason", "") == reason
            and origin is not None and _origin(values.get("origin", {})) == origin)


def check(manifest: dict, read_bytes: Callable[[str], bytes],
          snapshots: Mapping[str, Rows]) -> list[dict[str, str]]:
    """Check the pinned descriptor and every projected row against verified snapshots."""
    entries = [entry for entry in (manifest.get("compiled") or ())
               if isinstance(entry, dict) and entry.get("file") == FILE]
    if not entries:
        return []
    [entry, *additional] = entries
    if additional or not isinstance(entry.get("uri"), str) or not isinstance(entry.get("sha256"), str):
        return [{"reason": "malformed_state_projection_metadata"}]
    try:
        data = read_bytes(entry["uri"])
    except (KeyError, OSError):
        return [{"reason": "missing_state_projection_metadata"}]
    if not isinstance(data, bytes):
        return [{"reason": "missing_state_projection_metadata"}]
    if sha256_hex(data) != entry["sha256"]:
        return [{"reason": "state_projection_metadata_hash_mismatch"}]
    try:
        projections = _projections(data)
    except ValueError:
        return [{"reason": "malformed_state_projection_metadata"}]

    findings = []
    for projection in projections:
        source = snapshots.get(projection.source_relation, {})
        rows = snapshots.get(projection.relation, {})
        if any(not _matches(projection, parts, values, source) for parts, values in rows.values()):
            findings.append({"reason": "state_projection_evidence_mismatch", "relation": projection.relation})
    return findings
