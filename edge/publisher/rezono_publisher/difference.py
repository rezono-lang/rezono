"""What a proposal or variant changes, per role (step 7; docs/gui.md, "suppose in profile edge").

  python -m rezono_publisher.difference PACK MANIFEST [--profile p | --store url]

A proposal or variant manifest (`p-…`, `v-…`) names its base, a main manifest. Per role the gate serves (a
filtered role: `complete: false`) that both manifests have, this step writes under
`<pack>/<manifest>/<role>/explain/`:

    difference/<relation>   the role's two snapshots compared, as key-range trees (rezono_publisher.proof):
                            per changed row one entry, by key: {"key", "change": "added" | "removed"}, or
                            {"key", "change": "changed", "was"} for a changed cell (see `entries`)
    proof/<tree>/<relation> the target's proof graph for the role, as the views of a main manifest have it;
                            for a variant only the trees that are not the base's own (`shared`)
    index.json              rezono.explain-index/1: the hashes of both sides' snapshots, a count per relation
                            and the roots; written last. A variant's proof root is the base's, under
                            `<pack>/<base>/<role>/views/proof/`, where the base has the same tree

Both sides are what the role reads, so the difference shows nothing else. The checker compares the two
snapshots on its own (rezono_checker.difference) and rebuilds the proof graph (rezono_checker.proof) before
anything is written. The manifest stays as it is. A repeat writes the same bytes, so a run that stopped
is completed by the next.

Exit 0: written (or already there). Exit 2: a check failed, nothing written. Exit 1: an error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

from rezono_checker.difference import check_difference
from rezono_checker.rules import load_seals

from . import proof, timing, views
from .access import ACCESS
from . import store as stores

INDEX = "rezono.explain-index/1"
Blocked = views.Blocked  # a check failed: nothing of that manifest's difference is written
TREE = "difference"
TARGET = re.compile(r"^(p|v)-.+-(\d+)$")
OPS = ("insert", "delete", "set", "unset")  # contracts/delta.yaml; any other op is withheld (fail closed)
MEMBERSHIP = ("insert", "delete")  # the ops that write a kind's own table k(id)


def entries(before: bytes, after: bytes) -> list[dict]:
    """The changed rows of one relation, by key.

    A row in one snapshot only is `added` or `removed`. A changed cell is the one exception: a key of two or
    more columns whose prefix (all columns but the last) holds exactly one row on each side, and those two
    differ; it is one entry, `changed`, with the new key and the old one as `was`. So a single-valued
    attribute that takes another value reads as one change, and every other change as rows."""
    b = {tuple(r["key"]) for r in json.loads(before)}
    a = {tuple(r["key"]) for r in json.loads(after)}
    removed, added = b - a, a - b
    width_b = Counter(k[:-1] for k in b if len(k) > 1)
    width_a = Counter(k[:-1] for k in a if len(k) > 1)
    was = {k[:-1]: k for k in removed if len(k) > 1 and width_b[k[:-1]] == 1 and width_a[k[:-1]] == 1}
    out = []
    for k in added:
        if len(k) > 1 and k[:-1] in was:
            out.append({"key": list(k), "change": "changed", "was": list(was[k[:-1]])})
        else:
            out.append({"key": list(k), "change": "added"})
    paired = {tuple(e["was"]) for e in out if e["change"] == "changed"}
    out += [{"key": list(k), "change": "removed"} for k in removed if k not in paired]
    return sorted(out, key=lambda e: e["key"])


def plan_role(st, pack: str, manifest: str, m: dict, base: dict, role: str):
    """One role's objects, the index last; raises views.Blocked if a check fails."""
    def mine(man):
        snaps = sorted((s for s in man["snapshots"] if s["role"] == role), key=lambda s: s["relation"])
        return snaps, views._snapshots(st, snaps)

    base_snaps, before = mine(base)
    target_snaps, after = mine(m)
    at = f"{pack}/{manifest}/{role}/explain"
    made, counts, trees = [], {}, {}
    for rel in sorted(set(before) | set(after)):
        rs = entries(before.get(rel, b"[]"), after.get(rel, b"[]"))
        if not rs:
            continue
        c = Counter(e["change"] for e in rs)
        counts[rel] = {k: c[k] for k in ("added", "removed", "changed")}
        try:
            root, levels, files = proof.tree(TREE, rel, rs, lambda lv, n: f"difference/{rel}/{lv}/{n}.json")
        except proof.TooLarge as err:
            raise views.Blocked(f"role {role}: difference: {err}") from err
        made += [(f"{at}/{path}", data) for path, data in sorted(files.items())]
        trees[rel] = {"file": root, "sha256": proof.sha256(files[root]), "levels": levels}
    with timing.phase("checker"):
        problems = check_difference(before, after, {k.removeprefix(at + "/"): b for k, b in made}, counts, trees,
                                    proof.PIECE, proof.FANOUT)
    if problems:
        raise views.Blocked(f"role {role}: difference: {len(problems)} (first: {'; '.join(problems[:3])})")
    made_proof, proof_part = views._proof(st, pack, manifest, m, role, after, base=at)
    if m.get("variant"):
        made_proof, proof_part = shared(st, pack, base["id"], role, at, made_proof, proof_part)
    index = {
        "format": INDEX,
        "pack": pack,
        "manifest": manifest,
        "base_manifest": base["id"],
        "role": role,
        "base": [{"relation": s["relation"], "sha256": s["sha256"]} for s in base_snaps],
        "target": [{"relation": s["relation"], "sha256": s["sha256"]} for s in target_snaps],
        "difference": {"format": proof.INDEX, "piece": proof.PIECE, "fanout": proof.FANOUT, "counts": counts,
                       "trees": {rel: {"uri": st.uri(f"{at}/{r['file']}"), "sha256": r["sha256"], "levels": r["levels"]}
                                 for rel, r in trees.items()}},
        "proof": proof_part,
    }
    return made + made_proof + [(f"{at}/index.json", views.dumps(index))]


def shared(st, pack: str, base: str, role: str, at: str, made: list, part: dict):
    """A variant's proof graph with the trees that are the base's own named, not written again: (pieces, the
    `proof` part of the index). The manifest follows the same rule for a snapshot (rezono_publisher.publish).

    Every tree is made and checked first (views._proof); this only decides where a tree is read from. A tree
    is the base's when the role's view index of the base, with the same piece layout, names that tree with
    the same sha256 and levels at the same path under `<pack>/<base>/<role>/views`. A page names its children
    by sha256, so one root hash is one tree, piece for piece. Equality is that hash and nothing else; a tree
    the base does not have so, or a base without a view index, keeps the variant's copy."""
    raw = st.get(views.index_key(pack, base, role))
    theirs = json.loads(raw).get("proof") if raw else None
    if not theirs or any(theirs.get(k) != part[k] for k in ("format", "piece", "fanout")):
        return made, part
    there = f"{pack}/{base}/{role}/views"
    trees, gone = {}, []
    for t, by in part["trees"].items():
        trees[t] = {}
        for rel, mine in by.items():
            named = mine | {"uri": st.uri(there + views.key_of(mine["uri"]).removeprefix(at))}
            same = theirs.get("trees", {}).get(t, {}).get(rel) == named
            trees[t][rel] = named if same else mine
            if same:
                gone.append(f"{at}/proof/{t}/{rel}/")
    return [f for f in made if not f[0].startswith(tuple(gone))], part | {"trees": trees}


def plan(st, pack: str, manifest: str, delta: dict | None = None) -> list[tuple[str, bytes]]:
    """Every object to write, each role's index after its pieces, all made and checked first. Nothing for a
    delta that may change a right (`withheld`), or without the delta to decide it by."""
    if not TARGET.match(manifest):
        raise ValueError(f"{manifest}: a difference is made for a proposal or variant manifest only")
    m = json.loads(views._get(st, f"{pack}/manifests/{manifest}.json"))
    if not (m.get("proposal") or m.get("variant")) or not m.get("base_manifest"):
        raise ValueError(f"{manifest}: not a proposal or variant manifest with a base")
    base = json.loads(views._get(st, f"{pack}/manifests/{m['base_manifest']}.json"))
    if not views.MAIN.match(base.get("id", "")) or base.get("proposal") or base.get("variant"):
        raise ValueError(f"{manifest}: its base {m['base_manifest']} is not a main manifest")
    if withheld(_compiled(st, base, "ir/rules.json"), _compiled(st, base, "bundle/schema-bundle.json"), delta):
        return []
    served = {s["role"] for s in m["snapshots"] if s.get("complete") is False}
    served &= {s["role"] for s in base["snapshots"] if s.get("complete") is False}
    files = []
    for role in sorted(served):
        files += plan_role(st, pack, manifest, m, base, role)
    return files


def _compiled(st, man: dict, file: str):
    c = next((c for c in man.get("compiled", []) if c.get("file") == file), None)
    return json.loads(views._get(st, views.key_of(c["uri"]), c["sha256"])) if c else None


def withheld(rules_doc: dict | None, bundle: dict | None, delta: dict | None) -> bool:
    """True if a delta may change what a role reads: then no role gets a difference (docs/gui.md, "suppose in
    profile edge").

    Decided from the rules and the delta alone, never from data, so it is the same whether or not an element
    exists that a role does not see (no existence leak). A delta changes facts, never rules, but `may_read` is
    derived from facts. A change writes the relations of its kind and the kinds above it (an element of a
    subkind is one of its parent), and their slots (`<kind>__<slot>`). It may change a right if one of them is
    in the dependency closure of `may_read` (its body relations, through derived ones, to base ones), except an
    insert into a kind that only grants itself: every rule over it in that closure is `may_read(?r, "K", ?x)`
    with `K(?x)` positive in its body, so inserting K(x0) grants x0 alone, the delta's own content. Without
    the delta, or without its rules or bundle, it is withheld (fail closed).

    A base relation of the rules is a schema table, except two kinds the compiler makes from other tables:
    - A seal's relations (`k__refused`, `k__accepted`, `k__row_sha256`, each `p__accepted`) follow
      from the sealed kind, every part and the closes. With one of them in the closure, a change to any table
      the seal reads is withheld, whatever its op: an edited part refuses its element, which can grant a right.
    - A calculation selection (`calc__…`, role `calc`) follows from whatever the calculation reads. The
      compiler and the checker refuse a `may_read` that depends on one; if one arrives, it is withheld."""
    if delta is None or bundle is None:
        return True
    try:
        seals = load_seals(rules_doc or {})
    except (ValueError, AttributeError, TypeError):
        return True
    rules = (rules_doc or {}).get("rules", [])
    heads = {r["head"]["relation"] for r in rules}
    closure, todo = set(), [ACCESS]
    while todo:
        head = todo.pop()
        for r in rules:
            if r["head"]["relation"] == head:
                for x in (*r.get("body", []), *r.get("aggregates", [])):
                    if x["relation"] not in closure:
                        closure.add(x["relation"])
                        todo.append(x["relation"])
    over = [r for r in rules if r["head"]["relation"] in (closure & heads) | {ACCESS}]
    if any(r.get("role") == "calc" and r.get("name") in closure for r in (rules_doc or {}).get("relations", [])):
        return True
    sealed = set()  # every table a seal relation in the closure is computed from
    for s in seals:
        parts = s.get("parts", [])
        if closure & {s["refused"], s["accepted"], s["row_sha256"], *(p["accepted"] for p in parts)}:
            sealed |= {s["kind"], s["period"], *s["tables"], s["closed_until"], s["covers"], s["element"], s["sha256"]}
            sealed |= {t for p in parts for t in (p["kind"], p["arrow"], *p["tables"])}

    def grants_itself(kind):
        uses = [(r, x) for r in over for x in (*r.get("body", []), *r.get("aggregates", [])) if x["relation"] == kind]
        return all(r["head"]["relation"] == ACCESS and x in r.get("body", []) and x.get("polarity") == "positive"
                   and len(x["terms"]) == 1 and x["terms"][0].startswith("?")
                   and r["head"]["terms"][1:] == [kind, x["terms"][0]] for r, x in uses)

    parent = {k["id"]: k.get("parent") for k in bundle.get("kinds", [])}
    for ch in delta.get("changes", []):
        if not isinstance(ch, dict) or not isinstance(ch.get("kind"), str) or ch.get("op") not in OPS:
            return True
        op, chain, k = ch["op"], [], ch["kind"]
        while k and k not in chain:
            chain.append(k)
            k = parent.get(k)
        if any(t == k or t.startswith(f"{k}__") for t in sealed for k in chain):
            return True
        for rel in closure:
            if any(rel.startswith(f"{k}__") for k in chain):
                return True
            # Only an insert or a delete writes a kind's own table: a set or an unset needs the record as it
            # is and never changes its identifier or kind (the canonical writer), so membership stays.
            if rel in chain and op in MEMBERSHIP and not (op == "insert" and grants_itself(rel)):
                return True
    return False


def publish(st, pack: str, manifest: str, delta: dict | None = None) -> list[str]:
    """Make, check and write the differences of a manifest, for its delta (`withheld` decides by it). Returns
    the keys of the indexes written."""
    timing.switch("views")  # the difference is made like the views: from the store
    files = plan(st, pack, manifest, delta)
    timing.switch("upload")
    last = [f[0].endswith("/explain/index.json") for f in files]
    stores.put_all(st, [f for f, x in zip(files, last) if not x])  # concurrently; each role's index after its pieces
    stores.put_all(st, [f for f, x in zip(files, last) if x])
    return [key for (key, _), x in zip(files, last) if x]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publisher.difference")
    p.add_argument("pack")
    p.add_argument("manifest")
    p.add_argument("--profile", help="deploy profile with the section storage")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    args = p.parse_args(argv)
    from .__main__ import profile_settings

    url, endpoint, _ = profile_settings(args.profile) if args.profile else (None, None, {})
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    try:
        for key in publish(stores.open_store(url, endpoint), args.pack, args.manifest):
            print(key)
    except Blocked as err:
        print(f"blocked: {err}", file=sys.stderr)
        return 2
    except (stores.Conflict, ValueError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
