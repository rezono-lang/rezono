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

from rezono_checker import access as checker_access
from rezono_checker.difference import check_difference
from rezono_checker.rules import load_seals

from . import proof, timing, views
from .access import ACCESS, READ_FULL
from . import store as stores

INDEX = "rezono.explain-index/1"
Blocked = views.Blocked  # a check failed: nothing of that manifest's difference is written
TREE = "difference"
TARGET = re.compile(r"^(p|v)-.+-(\d+)$")
OPS = ("insert", "delete", "set", "unset")  # contracts/delta.yaml; any other op is withheld (fail closed)
MEMBERSHIP = ("insert", "delete")  # the ops that write a kind's own table k(id)


def _independent_tables(bundle: dict | None) -> frozenset[str]:
    """Tables whose rows are independent memberships (`multivalued: true` slots and `kinds`) from `bundle`."""
    if bundle is None:
        return frozenset()
    if not isinstance(bundle, dict):
        raise views.Blocked("difference: malformed schema bundle")
    fmt = bundle.get("format")
    if fmt is not None and fmt != "rezono.schema-bundle/1":
        raise views.Blocked("difference: malformed schema bundle format")
    if not any(section in bundle for section in ("kinds", "attributes", "arrows")):
        raise views.Blocked("difference: malformed schema bundle")
    cardinality: dict[str, bool] = {}
    for section in ("attributes", "arrows"):
        if section not in bundle:
            continue
        items = bundle[section]
        if not isinstance(items, list):
            raise views.Blocked(f"difference: malformed schema bundle {section}")
        for entry in items:
            if not isinstance(entry, dict):
                raise views.Blocked(f"difference: malformed schema bundle {section} entry")
            table = entry.get("table")
            mv = entry.get("multivalued")
            if not isinstance(table, str) or not table or type(mv) is not bool:
                raise views.Blocked(f"difference: malformed schema bundle {section} entry")
            if table in cardinality:
                raise views.Blocked(f"difference: duplicate schema slot table {table!r}")
            cardinality[table] = mv
    kind_tables: set[str] = set()
    if "kinds" in bundle:
        kinds = bundle["kinds"]
        if not isinstance(kinds, list):
            raise views.Blocked("difference: malformed schema bundle kinds")
        for entry in kinds:
            if not isinstance(entry, dict):
                raise views.Blocked("difference: malformed schema bundle kinds entry")
            table = entry["table"] if "table" in entry else entry.get("id")
            if not isinstance(table, str) or not table:
                raise views.Blocked("difference: malformed schema bundle kinds entry")
            if table in cardinality or table in kind_tables:
                raise views.Blocked(f"difference: duplicate schema table {table!r}")
            kind_tables.add(table)
    return frozenset(table for table, mv in cardinality.items() if mv) | frozenset(kind_tables)


def entries(before: bytes, after: bytes, *, multivalued: bool = False) -> list[dict]:
    """The changed rows of one relation, by key.

    A row in one snapshot only is `added` or `removed`. When `multivalued` is False (a single-valued
    schema slot or a non-slot multi-column relation), a key of two or more columns whose prefix (all
    columns but the last) holds exactly one row on each side and those two differ is one `changed`
    entry with the new key and the old one as `was`. When `multivalued` is True (a multivalued schema
    slot), every row is an independent set membership (`added` or `removed`) and distinct values never
    pair as `changed`."""
    if type(multivalued) is not bool:
        raise ValueError("multivalued must be a bool")
    b = {tuple(r["key"]) for r in json.loads(before)}
    a = {tuple(r["key"]) for r in json.loads(after)}
    removed, added = b - a, a - b
    if multivalued:
        out = ([{"key": list(k), "change": "added"} for k in added]
               + [{"key": list(k), "change": "removed"} for k in removed])
        return sorted(out, key=lambda e: e["key"])
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


def plan_role(st, pack: str, manifest: str, m: dict, base: dict, role: str, bundle: dict | None = None):
    """One role's objects, the index last; raises views.Blocked if a check fails."""
    def mine(man):
        snaps = sorted((s for s in man["snapshots"] if s["role"] == role), key=lambda s: s["relation"])
        return snaps, views._snapshots(st, snaps)

    if bundle is None:
        bundle = _compiled(st, base, "bundle/schema-bundle.json")
    independent = _independent_tables(bundle)
    base_snaps, before = mine(base)
    target_snaps, after = mine(m)
    at = f"{pack}/{manifest}/{role}/explain"
    made, counts, trees = [], {}, {}
    for rel in sorted(set(before) | set(after)):
        b_bytes, a_bytes = before.get(rel, b"[]"), after.get(rel, b"[]")
        if b_bytes == a_bytes:
            continue
        rs = entries(b_bytes, a_bytes, multivalued=True) if rel in independent else entries(b_bytes, a_bytes)
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
                                    proof.PIECE, proof.FANOUT, bundle=bundle)
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
    rules_doc = _compiled(st, base, "ir/rules.json")
    bundle = _compiled(st, base, "bundle/schema-bundle.json")
    pub_withheld = withheld(rules_doc, bundle, delta)
    with timing.phase("checker"):
        chk_withheld = checker_access.may_change_access(rules_doc, bundle, delta)
    if type(pub_withheld) is not bool or type(chk_withheld) is not bool or pub_withheld != chk_withheld:
        raise views.Blocked(
            f"access-change check disagreement: publisher={pub_withheld}, checker={chk_withheld}"
        )
    if pub_withheld:
        return []
    served = {s["role"] for s in m["snapshots"] if s.get("complete") is False}
    served &= {s["role"] for s in base["snapshots"] if s.get("complete") is False}
    files = []
    for role in sorted(served):
        files += plan_role(st, pack, manifest, m, base, role, bundle=bundle)
    return files


def _compiled(st, man: dict, file: str):
    c = next((c for c in man.get("compiled", []) if c.get("file") == file), None)
    return json.loads(views._get(st, views.key_of(c["uri"]), c["sha256"])) if c else None


def withheld(rules_doc: dict | None, bundle: dict | None, delta: dict | None) -> bool:
    """True if a delta may change what a role reads: then no role gets a difference (docs/gui.md, "suppose in
    profile edge").

    Decided from the rules and the delta alone, never from data, so it is the same whether or not an element
    exists that a role does not see (no existence leak). A delta changes facts, never rules, but `may_read`
    and `may_read_full` are derived from facts. A change writes the relations of its kind and the kinds above
    it (an element of a subkind is one of its parent), and their slots (`<kind>__<slot>`). It may change a
    right if one of them is in the dependency closure of `may_read` or `may_read_full` (their body and
    aggregate relations, through derived ones, to base ones), except an insert into a kind that only grants
    itself: every rule over it in that closure is `may_read(?r, "K", ?x)` with `K(?x)` positive in its body
    (and `may_read` itself does not feed further access rules), so inserting K(x0) grants x0 alone, the
    delta's own content, and never changes `may_read_full`. Without the delta or bundle, or on malformed
    inputs, it is withheld (fail closed).

    A base relation of the rules is a schema table, except two kinds the compiler makes from other tables:
    - A seal's relations (`k__refused`, `k__accepted`, `k__row_sha256`, each `p__accepted`) follow
      from the sealed kind, every part and the closes. With one of them in the closure, a change to any table
      the seal reads is withheld, whatever its op: an edited part refuses its element, which can grant a right.
    - A calculation selection (`calc__…`, role `calc`) follows from whatever the calculation reads. The
      compiler and the checker refuse access rules that depend on one; if one arrives, it is withheld."""
    if not isinstance(delta, dict) or not isinstance(bundle, dict):
        return True
    if rules_doc is not None and not isinstance(rules_doc, dict):
        return True
    doc = {} if rules_doc is None else rules_doc
    fmt = doc.get("format")
    if fmt is not None and fmt != "rezono.rules/1":
        return True
    if "seals" in doc and not isinstance(doc["seals"], list):
        return True
    try:
        seals = load_seals(doc)
    except (ValueError, AttributeError, TypeError, KeyError):
        return True
    if not isinstance(bundle.get("kinds"), list) or not isinstance(delta.get("changes"), list):
        return True
    if ("rules" in doc and not isinstance(doc["rules"], list)) or ("relations" in doc and not isinstance(doc["relations"], list)):
        return True
    parent: dict[str, str | None] = {}
    for entry in bundle["kinds"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"] or entry["id"] in parent:
            return True
        par = entry.get("parent")
        if par is not None and (not isinstance(par, str) or not par):
            return True
        parent[entry["id"]] = par
    chains: dict[str, list[str]] = {}
    for kid in parent:
        chain, cur = [], kid
        while cur is not None:
            if cur not in parent or cur in chain:
                return True
            chain.append(cur)
            cur = parent[cur]
        chains[kid] = chain
    inlined_arrows: dict[str, list[str]] = {}
    if "arrows" in bundle:
        if not isinstance(bundle["arrows"], list):
            return True
        for arrow in bundle["arrows"]:
            if not isinstance(arrow, dict):
                return True
            src, dst = arrow.get("kind"), arrow.get("target")
            if (not isinstance(src, str) or not src or src not in parent
                    or not isinstance(dst, str) or not dst or dst not in parent):
                return True
            if "inlined" in arrow:
                if not isinstance(arrow["inlined"], bool):
                    return True
                if arrow["inlined"]:
                    inlined_arrows.setdefault(src, []).append(dst)
    rules = doc.get("rules", [])
    for r in rules:
        if not isinstance(r, dict) or not isinstance(r.get("head"), dict):
            return True
        head = r["head"]
        if (not isinstance(head.get("relation"), str) or not head["relation"]
                or not isinstance(head.get("terms"), list) or not all(isinstance(t, str) for t in head["terms"])):
            return True
        if ("body" in r and not isinstance(r["body"], list)) or ("aggregates" in r and not isinstance(r["aggregates"], list)):
            return True
        for x in r.get("body", []):
            pol = x.get("polarity") if isinstance(x, dict) else None
            if (not isinstance(x, dict) or not isinstance(x.get("relation"), str) or not x["relation"]
                    or not isinstance(x.get("terms"), list) or not all(isinstance(t, str) for t in x["terms"])
                    or (pol is not None and (not isinstance(pol, str) or pol not in ("positive", "negative")))):
                return True
        for x in r.get("aggregates", []):
            if not isinstance(x, dict) or not isinstance(x.get("relation"), str) or not x["relation"]:
                return True
    relations = doc.get("relations", [])
    for r in relations:
        if not isinstance(r, dict):
            return True
        if r.get("role") == "calc" and (not isinstance(r.get("name"), str) or not r["name"]):
            return True

    roots = {ACCESS, READ_FULL}
    heads = {r["head"]["relation"] for r in rules}
    closure, seen, todo = set(), set(roots), list(roots)
    while todo:
        head = todo.pop()
        for r in rules:
            if r["head"]["relation"] == head:
                for x in (*r.get("body", []), *r.get("aggregates", [])):
                    rel = x["relation"]
                    closure.add(rel)
                    if rel not in seen:
                        seen.add(rel)
                        todo.append(rel)
    over = [r for r in rules if r["head"]["relation"] in (closure & heads) | roots]
    if any(r.get("role") == "calc" and r.get("name") in (closure | roots) for r in relations):
        return True
    sealed = set()  # every table a seal relation in the closure is computed from
    for s in seals:
        parts = s.get("parts", [])
        if closure & {s["refused"], s["accepted"], s["row_sha256"], *(p["accepted"] for p in parts)}:
            sealed |= {s["kind"], s["period"], *s["tables"], s["closed_until"], s["covers"], s["element"], s["sha256"]}
            sealed |= {t for p in parts for t in (p["kind"], p["arrow"], *p["tables"])}

    def grants_itself(kind):
        if ACCESS in closure:
            return False
        body_uses = [(r, x) for r in over for x in r.get("body", []) if x["relation"] == kind]
        agg_uses = [x for r in over for x in r.get("aggregates", []) if x["relation"] == kind]
        if agg_uses or not body_uses:
            return False
        return all(r["head"]["relation"] == ACCESS and x.get("polarity") == "positive"
                   and len(x["terms"]) == 1 and x["terms"][0].startswith("?")
                   and len(r["head"]["terms"]) == 3 and r["head"]["terms"][1:] == [kind, x["terms"][0]]
                   for r, x in body_uses)

    for ch in delta["changes"]:
        if (not isinstance(ch, dict) or not isinstance(ch.get("op"), str) or ch["op"] not in OPS
                or not isinstance(ch.get("kind"), str) or not ch["kind"] or ch["kind"] not in chains):
            return True
        op, chain = ch["op"], chains[ch["kind"]]
        inlined_reached, expanded, work = set(), set(chain), list(chain)
        while work:
            owner = work.pop()
            for target in inlined_arrows.get(owner, ()):
                for anc in chains[target]:
                    inlined_reached.add(anc)
                    if anc not in expanded:
                        expanded.add(anc)
                        work.append(anc)
        touched = set(chain) | inlined_reached
        if any(t == k or t.startswith(f"{k}__") for t in sealed for k in touched):
            return True
        for rel in closure:
            if rel in inlined_reached or any(rel.startswith(f"{k}__") for k in touched):
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
