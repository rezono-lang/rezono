"""Authenticate state projections against the epoch's independently archived Values."""

import json
from collections.abc import Callable, Collection, Mapping
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


def _evidence(projection: Projection, original: Values) -> tuple[str, str, str] | None:
    value = original.get(projection.value_column)
    origin = _origin(original.get(projection.origin_column, {}))
    if value is None or origin is None:
        return None
    state, reason = value["state"], value.get("reason", "")
    if not isinstance(state, str) or not isinstance(reason, str):
        return None
    return state, reason, origin


def _matches(projection: Projection, parts: tuple[str, ...], values: Values, source: Rows) -> bool:
    if len(parts) != 3:
        return False
    subject, state, reason = parts
    row = source.get(encode_key((subject,)))
    if row is None:
        return False
    origin = _origin(values.get("origin", {}))
    return origin is not None and _evidence(projection, row[1]) == (state, reason, origin)


def _expected(projection: Projection, source: Rows) -> set[str] | None:
    expected = set()
    for parts, original in source.values():
        # A descriptor's required flag cannot turn an omitted Value into evidence of a state.
        if projection.value_column not in original:
            continue
        evidence = _evidence(projection, original)
        if len(parts) != 1 or evidence is None:
            return None
        state, reason, _ = evidence
        expected.add(encode_key((*parts, state, reason)))
    return expected


def check(manifest: dict, read_bytes: Callable[[str], bytes],
          snapshots: Mapping[str, Rows], *, full: Collection[str] | None = None) -> list[dict[str, str]]:
    """Check each row's evidence and require equality when both snapshot scopes are complete."""
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
        scope = (projection.source_relation, projection.relation)
        complete = full is None or (projection.source_relation in full and projection.relation in full)
        if complete:
            missing = [relation for relation in scope if relation not in snapshots]
            if missing:
                findings.extend({"reason": "state_projection_snapshot_missing", "relation": relation}
                                for relation in missing)
                continue
        source = snapshots.get(projection.source_relation, {})
        rows = snapshots.get(projection.relation, {})
        if any(not _matches(projection, parts, values, source) for parts, values in rows.values()):
            findings.append({"reason": "state_projection_evidence_mismatch", "relation": projection.relation})
        if complete:
            # Per-row evidence rules out extra keys. All authenticated source state keys must also be present.
            expected = _expected(projection, source)
            if expected is None:
                findings.append({"reason": "state_projection_source_unverifiable", "relation": projection.source_relation})
            elif expected - rows.keys():
                findings.append({"reason": "state_projection_incomplete", "relation": projection.relation})
    return findings
