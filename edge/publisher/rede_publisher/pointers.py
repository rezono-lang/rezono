"""Pointers to manifests, so the gate never lists or reads every manifest (docs/gui.md, O(page), step 4).

  python -m rede_publisher.pointers PACK [--profile p | --store url]

Every object is written once, so the newest manifest cannot be one object that changes. Instead each main
manifest gets a *head*, written once right after it:

  <pack>/heads/<10^19 - 1 - epoch, 19 digits>.json   {"format": "rede.head/1", "manifest", "epoch", "sha256"}

A store lists keys in order, so the first key under `<pack>/heads/` is the newest main manifest: one list of
one key. The gate reads it, then the manifest by its key, and checks the sha256 the head names. A pack without
a head has no publication for the gate (fail closed).

The other manifests and the diagnoses get a *pointer* the same way, so the gate lists only what one answer
needs:

  <pack>/epochs/<epoch>/manifests/<id>.json   a sweep's variant, by its epoch (the gate reads now + 1)
  <pack>/epochs/<epoch>/diagnoses/<id>.json   a red variant's diagnosis, likewise
  <pack>/bases/<base manifest>/<id>.json      a proposal manifest, by the manifest it is against
                                              each {"format": "rede.pointer/1", "id", "sha256"}

`backfill` writes every head and pointer of the objects already in the store that has none: the same bytes the
publisher writes, made from each object's own bytes, so it is idempotent and deterministic, and one that is
there with other bytes is a Conflict. Exit 0: done; 1: an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

from . import store as stores

HEAD = "rede.head/1"
POINTER = "rede.pointer/1"
TOP = 10**19 - 1
MAIN = re.compile(r"^m-(\d+)$")


def head_key(pack: str, epoch: int) -> str:
    if not 0 <= epoch <= TOP:
        raise ValueError(f"epoch {epoch} is out of range")
    return f"{pack}/heads/{TOP - epoch:019d}.json"


def is_main(m: dict) -> bool:
    return not m.get("proposal") and m.get("variant") is None and bool(MAIN.match(m.get("id", "")))


def head(pack: str, manifest_bytes: bytes) -> tuple[str, bytes] | None:
    """The head of a main manifest, from its bytes: (key, bytes); None for a proposal or a variant."""
    m = json.loads(manifest_bytes)
    if not is_main(m):
        return None
    body = {"format": HEAD, "manifest": m["id"], "epoch": m["epoch"], "sha256": hashlib.sha256(manifest_bytes).hexdigest()}
    return head_key(pack, m["epoch"]), json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def pointers(pack: str, kind: str, data: bytes) -> list[tuple[str, bytes]]:
    """Every head or pointer of one object (`kind`: manifests or diagnoses), from its bytes."""
    o = json.loads(data)
    sha = hashlib.sha256(data).hexdigest()
    if kind == "manifests" and is_main(o):
        return [head(pack, data)]
    ref = dumps({"format": POINTER, "id": o["id"], "sha256": sha})
    if kind == "diagnoses" or o.get("variant") is not None:
        return [(f"{pack}/epochs/{o['epoch']}/{kind}/{o['id']}.json", ref)]
    if o.get("proposal") and o.get("base_manifest"):
        return [(f"{pack}/bases/{o['base_manifest']}/{o['id']}.json", ref)]
    return []


def write(st, pack: str, kind: str, data: bytes) -> list[str]:
    """Writes the heads and pointers of one object that are not there yet; returns their keys."""
    out = []
    for key, body in pointers(pack, kind, data):
        if st.get(key) != body:
            st.put_new(key, body)  # one with other bytes raises Conflict
            out.append(key)
    return out


def backfill(st, pack: str) -> list[str]:
    """Writes the missing heads and pointers of the pack's manifests and diagnoses; returns the keys written.

    Every object is read and checked first, then the heads are written newest first, then the pointers: the
    gate takes the first head as the rights of now, so an older head alone (a backfill stopped halfway) must
    never be the first."""
    made = []
    for kind in ("manifests", "diagnoses"):
        for key in sorted(st.list(f"{pack}/{kind}/")):
            data = st.get(key) if key.endswith(".json") else None
            if data is None:
                continue
            try:
                o = json.loads(data)
            except ValueError as err:
                raise ValueError(f"{key} is not JSON") from err
            if key != f"{pack}/{kind}/{o.get('id')}.json":
                raise ValueError(f"{key} holds another object")
            made += pointers(pack, kind, data)
    heads = sorted(m for m in made if "/heads/" in m[0])  # the head key sorts the newest first
    written = []
    for key, body in heads + sorted(m for m in made if "/heads/" not in m[0]):
        if st.get(key) != body:
            st.put_new(key, body)  # one with other bytes raises Conflict
            written.append(key)
    return sorted(written)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rede_publisher.pointers")
    p.add_argument("pack", help="the pack's name, as in its store keys")
    p.add_argument("--profile", help="deploy profile with the section storage")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    args = p.parse_args(argv)
    from .__main__ import profile_settings

    url, endpoint, _ = profile_settings(args.profile) if args.profile else (None, None, {})
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    try:
        for key in backfill(stores.open_store(url, endpoint), args.pack):
            print(key)
    except (stores.Conflict, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
