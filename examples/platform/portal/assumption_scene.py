"""Publish a combined comparison scene for two published platform worlds."""

from __future__ import annotations

import json
from collections.abc import Sequence

from rezono_publisher import publish


def _read_side(store, pack: str, manifest: str, role: str, relations: Sequence[str]):
    objs = publish.role_objects(store, pack, manifest, role)
    if not objs:
        raise KeyError(f"missing manifest {manifest!r} or role {role!r} for pack {pack!r}")

    def load(name: str):
        key = objs.get(name)
        if key is None:
            raise KeyError(f"manifest {manifest!r} role {role!r} lacks {name!r}")
        raw = store.get(key)
        if raw is None:
            raise KeyError(f"missing store object {key!r}")
        return json.loads(raw)

    rows: dict[str, set[tuple[str, ...]]] = {}
    for rel in relations:
        rows[rel] = {tuple(entry["key"]) for entry in load(f"relations/{rel}.json")}

    witnesses: dict[tuple[str, tuple[str, ...]], dict] = {}
    for witness in load("witnesses.json")["witnesses"]:
        conclusion = witness["conclusion"]
        witnesses[(conclusion["relation"], tuple(json.loads(conclusion["key"])))] = witness

    return rows, witnesses


def publish_scene(store, pack: str, before: str, after: str, role: str, relations: Sequence[str]) -> str:
    """Write a combined assumption scene with signed deltas, witnesses and stable positions."""
    ordered_relations = tuple(relations)
    before_rows, before_witnesses = _read_side(store, pack, before, role, ordered_relations)
    after_rows, after_witnesses = _read_side(store, pack, after, role, ordered_relations)

    changes: list[dict] = []
    positions: list[dict] = []

    for rel in ordered_relations:
        removed = sorted(before_rows[rel] - after_rows[rel])
        added = sorted(after_rows[rel] - before_rows[rel])
        for key in removed:
            changes.append({
                "relation": rel,
                "key": list(key),
                "weight": -1,
                "witness": before_witnesses[(rel, key)],
            })
        for key in added:
            changes.append({
                "relation": rel,
                "key": list(key),
                "weight": 1,
                "witness": after_witnesses[(rel, key)],
            })

        combined = sorted(before_rows[rel] | after_rows[rel])
        slots = {key: index for index, key in enumerate(combined)}
        for side_id, side_rows in ((before, before_rows[rel]), (after, after_rows[rel])):
            for key in sorted(side_rows):
                positions.append({
                    "side": side_id,
                    "relation": rel,
                    "key": list(key),
                    "band": rel,
                    "slot": slots[key],
                })

    scene = {
        "format": "rezono.assumption-scene/1",
        "pack": pack,
        "before": before,
        "after": after,
        "role": role,
        "relations": list(ordered_relations),
        "changes": changes,
        "positions": positions,
    }
    data = publish.canonical(scene)
    key = f"{pack}/scenes/{before}/{after}/{role}/{publish.sha256(data)}.json"
    store.put_new(key, data)
    return key
