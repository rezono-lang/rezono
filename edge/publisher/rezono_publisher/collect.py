"""The collector (RV-Z01): delete from a pack's store what no retained manifest needs, by reachability.

  python -m rezono_publisher.collect PACK (--profile p | --store url) [--keep-main N] [--keep ID ...]
      [--open-proposals FILE] [--grace-seconds S] [--delete]

Without --delete it deletes nothing and prints what it would delete: a dry run. It is no step of a publication;
an operator or a scheduled job runs it.

Retained, the roots: the newest N main manifests by epoch (`--keep-main`, else the profile's
`publish.retention.main`; at least 1); every manifest named by `--keep` or the profile's `publish.retention.keep`
(a sealed one, one a retained calculation pins, one kept as evidence); and every proposal manifest whose proposal is
open (`--open-proposals`: a JSON list of the open proposals' ids, from the Git host port; without it every proposal
counts as open). Then, until nothing changes: the base of every retained manifest, and every variant whose base is
retained (the gate serves the variants of a main it serves).

Reachable: a retained manifest, its head or pointer, every object it names by uri (snapshots, witness sets, asset
indexes, source sets, compiled files, the build record), every image a named asset index names, and everything
under `<pack>/<manifest>/` of a retained manifest: its views and forms, written beside it and named by no manifest.
A diagnosis is reachable, with its pointer, when the manifest it names as its last good one is retained or its epoch
is not older than the oldest retained main manifest.

Deleted: every other key in the publisher's namespaces of the pack (manifests, diagnoses, heads, epochs, bases,
objects, assets, bundles, builds, and `<pack>/<id>/` of a manifest or diagnosis that is there) that was written
longer ago than the grace period (default one day). A publication writes its objects before its manifest, so what
no manifest names yet may be one in flight; the grace period must be longer than the longest publication and the
longest run of the job `forms` (whose forms follow a publication, twice forms.budget_minutes at most). Heads and
pointers go first, then manifests and diagnoses, then the rest, so no reader finds a head without its manifest or
a manifest without its objects. A key in no known namespace is left and counted.

The condition for whoever runs it: never beside a publication of the same pack (the job `publish`, a proposal, a
sweep), nor beside the job `forms`, which writes a published manifest's forms after it. The grace period protects
only what a publication writes. A key that is there already is not written again (conditional put), so it keeps its
old date: a publication that takes over an old object no retained manifest names (an image, a compiled file, a build
record, an object of a base outside the retained set) could lose it to a collector running at the same time. The
collector closes what it can see: it lists the manifests again right before its deletes, and again before the
objects, and stops when one is there that its plan did not read.

Fail closed, before anything is deleted: a manifest or diagnosis that is no JSON object; a retained manifest whose
asset index is missing or has other bytes than its hash, or that names a key the store does not list; no main
manifest retained; a served manifest (the one the newest head names, as the gate finds it) that is not retained, or
a newer main manifest without a head (a publication that did not finish); a kept id that is not in the store.
Exit 0: done; 1: an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time

from . import pointers
from . import store as stores

NAMESPACES = ("manifests", "diagnoses", "heads", "epochs", "bases", "objects", "assets", "bundles", "builds")
FIRST = ("heads", "epochs", "bases")  # deleted before the manifests they point to
THEN = ("manifests", "diagnoses")
SECTIONS = ("snapshots", "witnesses", "assets", "fact_sources", "compiled")
DAY = 86400


def key_of(uri: str) -> str:
    return re.sub(r"^s3://[^/]+/", "", uri)


def documents(st, pack: str, kind: str) -> dict[str, bytes]:
    """Every manifest or diagnosis of the pack by id, as bytes; a key whose bytes are no JSON object with that id
    stops the collector."""
    out = {}
    for key in st.list(f"{pack}/{kind}/"):
        name = key[len(f"{pack}/{kind}/"):]
        if "/" in name or not name.endswith(".json"):
            continue
        data = st.get(key)
        try:
            doc = json.loads(data)
        except (TypeError, ValueError) as err:
            raise ValueError(f"{key} is no JSON: {err}") from err
        if not isinstance(doc, dict) or doc.get("id") != name[:-5]:
            raise ValueError(f"{key} is not the {kind[:-1]} it is named after")
        out[name[:-5]] = data
    return out


def retained(manifests: dict[str, dict], keep_main: int, keep: set[str], open_proposals: set[str] | None) -> set[str]:
    """The ids of the manifests the collector keeps (see the module's docstring)."""
    if keep_main < 1:
        raise ValueError("--keep-main must be at least 1: the newest main manifest is what the gate serves")
    mains = sorted((m for m in manifests.values() if pointers.is_main(m)), key=lambda m: m["epoch"], reverse=True)
    out = {m["id"] for m in mains[:keep_main]} | (keep & set(manifests))
    out |= {i for i, m in manifests.items()
            if m.get("proposal") and (open_proposals is None or m["proposal"] in open_proposals)}
    while True:
        more = {manifests[i].get("base_manifest") for i in out} & set(manifests)
        more |= {i for i, m in manifests.items() if m.get("variant") is not None and m.get("base_manifest") in out}
        if more <= out:
            return out
        out |= more


def served(st, pack: str, manifests: dict[str, dict], keep: set[str]) -> None:
    """Stops unless what the gate serves stays: a main manifest is retained, the one the newest head names
    (`publish.newest_main`, as the gate finds it) is retained, and no main manifest is newer than it."""
    mains = [m for m in manifests.values() if pointers.is_main(m)]
    if not {m["id"] for m in mains} & keep:
        raise ValueError("no main manifest is retained: the gate would serve nothing of the pack")
    from .publish import newest_main

    head = newest_main(st, pack)  # a head that is not its manifest's raises
    if head is None:
        raise ValueError("no head: the gate serves nothing of the pack (write the heads: rezono_publisher.pointers)")
    newest = max(mains, key=lambda m: m["epoch"])
    if newest["id"] != head["id"]:
        raise ValueError(f"{newest['id']} is newer than the served {head['id']} and has no head: a publication that "
                         "did not finish (publish again, or write its head: rezono_publisher.pointers)")
    if head["id"] not in keep:
        raise ValueError(f"the served manifest {head['id']} (the newest head's) is not retained")


def named(st, mid: str, m: dict) -> set[str]:
    """The keys of every object a manifest names by uri, and of every image its asset indexes name."""
    entries = [e for s in SECTIONS for e in m.get(s, [])] + ([m["build"]] if m.get("build") else [])
    keys = {key_of(e["uri"]) for e in entries}
    for e in m.get("assets", []):  # the images an asset index names (decision B10)
        index = st.get(key_of(e["uri"]))
        if index is None or hashlib.sha256(index).hexdigest() != e["sha256"]:
            raise ValueError(f"{mid}: the asset index {e['uri']} is missing or not the bytes its hash names")
        keys |= {key_of(a["uri"]) for a in json.loads(index)}
    return keys


def reachable(st, pack: str, manifests: dict[str, bytes], diagnoses: dict[str, bytes], keep: set[str],
              listed: set[str] | None = None) -> set[str]:
    """Every key a retained manifest or diagnosis needs, except the `<pack>/<id>/` prefixes (see `needed`). With
    `listed` (the store's keys), stops when a retained manifest names an object that is not among them: a uri form
    `key_of` does not know would make every object of that manifest unreached."""
    keys = set()
    for mid in sorted(keep):
        data = manifests[mid]
        m = json.loads(data)
        keys.add(f"{pack}/manifests/{mid}.json")
        keys |= {k for k, _ in pointers.pointers(pack, "manifests", data) if k}
        objects = named(st, mid, m)
        if listed is not None and not objects <= listed:
            raise ValueError(f"{mid} names what the store does not list: {sorted(objects - listed)[0]}")
        keys |= objects
    mains = [json.loads(manifests[i]) for i in keep]
    oldest = min((m["epoch"] for m in mains if pointers.is_main(m)), default=None)
    for did, data in diagnoses.items():
        d = json.loads(data)
        if d.get("last_good_manifest") in keep or (oldest is not None and d.get("epoch", -1) >= oldest):
            keys.add(f"{pack}/diagnoses/{did}.json")
            keys |= {k for k, _ in pointers.pointers(pack, "diagnoses", data)}
    return keys


def plan(st, pack: str, *, keep_main: int, keep: set[str] = frozenset(), open_proposals: set[str] | None = None,
         grace: float = DAY, now: float | None = None) -> dict:
    """What the collector would delete, in order, and what it keeps; nothing is deleted here."""
    if grace < 0:
        raise ValueError("the grace period cannot be negative")
    manifests_bytes = documents(st, pack, "manifests")
    diagnoses = documents(st, pack, "diagnoses")
    manifests = {i: json.loads(b) for i, b in manifests_bytes.items()}
    keep_ids = retained(manifests, keep_main, set(keep), open_proposals)
    served(st, pack, manifests, keep_ids)
    dated = st.dated(f"{pack}/")
    needed = reachable(st, pack, manifests_bytes, diagnoses, keep_ids, {k for k, _ in dated})
    owned = set(manifests) | set(diagnoses)
    now = time.time() if now is None else now
    delete, young, unknown = [], 0, []
    for key, written in dated:
        top = key[len(pack) + 1:].split("/", 1)[0]
        if top in keep_ids or key in needed:
            continue
        if top not in NAMESPACES and top not in owned:
            unknown.append(key)
        elif written > now - grace:
            young += 1
        else:
            delete.append(key)
    rank = lambda k: (0 if k.split("/")[1] in FIRST else 1 if k.split("/")[1] in THEN else 2, k)
    return {"retained": sorted(keep_ids), "missing": sorted(set(keep) - set(manifests)), "read": sorted(manifests),
            "delete": sorted(delete, key=rank), "young": young, "unknown": sorted(unknown)}


def unchanged(st, pack: str, read: list[str]) -> None:
    """Stops when a manifest is in the store that the plan did not read: a publication ran beside the collector."""
    there = {k[len(f"{pack}/manifests/"):-5] for k in st.list(f"{pack}/manifests/") if k.endswith(".json")}
    new = sorted(there - set(read))
    if new:
        raise ValueError(f"published while the collector ran: {', '.join(new)}; nothing more is deleted")


def delete(st, pack: str, out: dict) -> None:
    """Delete what a plan names, in its order: the manifests are listed again right before the first delete and
    right before the first object, and a manifest the plan did not read stops it."""
    unchanged(st, pack, out["read"])
    objects = False
    for key in out["delete"]:
        if not objects and key.split("/")[1] not in FIRST + THEN:
            unchanged(st, pack, out["read"])
            objects = True
        st.delete(key)


def collect(st, pack: str, **kw) -> dict:
    """Delete what `plan` names, in its order (`delete`)."""
    out = plan(st, pack, **kw)
    delete(st, pack, out)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publisher.collect", description=__doc__.splitlines()[0])
    p.add_argument("pack", help="the pack's name, as in its store keys")
    p.add_argument("--profile", help="deploy profile with the sections storage and publish.retention")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    p.add_argument("--keep-main", type=int, help="how many of the newest main manifests to keep")
    p.add_argument("--keep", action="append", default=[], metavar="ID", help="a manifest to keep (repeatable)")
    p.add_argument("--open-proposals", help="a JSON list of the ids of the open proposals")
    p.add_argument("--grace-seconds", type=float, default=DAY)
    p.add_argument("--delete", action="store_true",
                   help="delete; without it, only print what would be deleted. Never beside a publication of the pack: "
                        "an old object a publication takes over keeps its old date")
    args = p.parse_args(argv)
    from .__main__ import profile_settings

    url, endpoint, _ = profile_settings(args.profile) if args.profile else (None, None, {})
    retention = {}
    if args.profile:
        import yaml

        with open(args.profile, encoding="utf-8") as f:
            retention = ((yaml.safe_load(f) or {}).get("publish") or {}).get("retention") or {}
    url = args.store or url
    keep_main = args.keep_main if args.keep_main is not None else retention.get("main")
    if not url:
        p.error("no store: give --store or a profile with storage")
    if keep_main is None:
        p.error("no retention: give --keep-main or a profile with publish.retention.main")
    opened = None
    if args.open_proposals:
        with open(args.open_proposals, encoding="utf-8") as f:
            listed = json.load(f)
        if not isinstance(listed, list) or not all(isinstance(x, str) for x in listed):
            p.error("--open-proposals: a JSON list of texts, the proposals' ids")
        opened = set(listed)
    try:
        st = stores.open_store(url, endpoint)
        out = plan(st, args.pack, keep_main=int(keep_main), keep=set(args.keep) | set(retention.get("keep") or []),
                   open_proposals=opened, grace=args.grace_seconds)
        absent = sorted(set(args.keep) & set(out["missing"]))
        if args.delete and absent:  # the profile's list is for every pack; a command line's is for this one
            raise ValueError(f"--keep names what the store does not hold: {', '.join(absent)}; nothing is deleted")
        if args.delete:
            delete(st, args.pack, out)
    except (ValueError, KeyError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    verb = "deleted" if args.delete else "would delete"
    for key in out["delete"]:
        print(f"{verb} {key}")
    print(f"{len(out['retained'])} manifests retained, {len(out['delete'])} keys {verb}, {out['young']} too young, "
          f"{len(out['unknown'])} in no known namespace" +
          (f"; not in the store: {', '.join(out['missing'])}" if out["missing"] else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
