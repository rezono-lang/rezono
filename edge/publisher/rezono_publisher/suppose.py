"""What if, locally on the batch engine (decisions/local-suppose.md).

  rezono-suppose PACK --store URL --base-manifest m-N --role ROLE --delta FILE

Takes a pack directory, a store, a published main manifest of that pack, one
role the base publishes as `may_read` and one delta (`contracts/delta.yaml`).
Copies the pack and every pack it imports by a relative path into a fresh work
directory, applies the delta with `rezono_compiler.writer.apply_delta`,
publishes the copy next to the base as proposal `local-<12 hex of the delta's
SHA-256>`, runs `rezono_publisher.difference.publish` with the delta, and reads
that role's checked difference back as `rezono.supposition/1`.

Exit 0: answered, also when withheld. Exit 2: the checker refused, nothing
written. Exit 1: an error.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import shutil
import sys
from pathlib import Path

import yaml
from rezono_canon import CanonError, canonical_json, canonical_sha256

from . import access, difference, pointers, publish, views
from . import store as stores

FORMAT = "rezono.supposition/1"
WITHHELD_REASON = "delta may change read access"


def proposal_name(delta: dict) -> str:
    """`local-` followed by the first twelve hex digits of the delta's canonical SHA-256 (RFC 8785)."""
    return f"local-{canonical_sha256(delta)[:12]}"


def _utc_instant(timestamp: str) -> str:
    """Normalise an ISO-8601 timestamp to UTC `YYYY-MM-DDTHH:MM:SSZ` for `source_writer.stated`."""
    if not isinstance(timestamp, str) or not timestamp:
        raise ValueError("base manifest has no knowledge_time")
    text = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
    dt = datetime.datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"knowledge_time must carry a timezone, not {timestamp!r}")
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _roles_of(base: dict, base_manifest: str) -> dict[str, str]:
    """The roles the base manifest publishes, mapped to `complete` or `may_read`."""
    roles: dict[str, str] = {}
    for snap in base.get("snapshots", []):
        role = snap.get("role")
        if not isinstance(role, str) or not role:
            raise ValueError(f"{base_manifest}: malformed snapshot role")
        mode = access.COMPLETE if snap.get("complete") else access.FILTERED
        if role in roles and roles[role] != mode:
            raise ValueError(f"{base_manifest}: conflicting access modes for role {role!r}")
        roles[role] = mode
    return roles


def _compiled(st, manifest: dict, file: str):
    entry = next((c for c in manifest.get("compiled", []) if c.get("file") == file), None)
    if entry is None:
        return None
    return json.loads(views._get(st, views.key_of(entry["uri"]), entry["sha256"]))


def _check_no_observations(bundle: dict | None, delta: dict) -> None:
    """Observations do not change under an assumption (decisions/local-suppose.md)."""
    if not isinstance(bundle, dict):
        return
    kinds = {
        k["id"]: k
        for k in bundle.get("kinds", [])
        if isinstance(k, dict) and isinstance(k.get("id"), str)
    }
    for ch in delta.get("changes", []):
        kind = ch.get("kind")
        cur = kind
        seen: set[str] = set()
        while isinstance(cur, str) and cur in kinds and cur not in seen:
            seen.add(cur)
            if kinds[cur].get("layer") == "observation":
                raise ValueError(
                    f"observations do not change under an assumption: kind {kind!r} has bundle layer 'observation'"
                )
            cur = kinds[cur].get("parent")


def _unset_totality_checks(bundle: dict | None, delta: dict) -> set[str]:
    """Totality check views for required slots explicitly unset by `delta`.

    In `contracts/delta.yaml`, `unset` on a required slot makes that slot unknown (never zero).
    Under a local assumption, the totality violation on that explicitly unset slot is recorded as
    a warning so the assumption can be published and its checked unknown values answered, while
    every other red check still blocks.
    """
    if not isinstance(bundle, dict):
        return set()
    parents = {
        k["id"]: k.get("parent")
        for k in bundle.get("kinds", [])
        if isinstance(k, dict) and isinstance(k.get("id"), str)
    }
    totality_views = {
        c["view"]
        for c in bundle.get("checks", [])
        if isinstance(c, dict) and c.get("check") == "totality" and isinstance(c.get("view"), str)
    }
    out: set[str] = set()
    for ch in delta.get("changes", []):
        if ch.get("op") != "unset":
            continue
        cur, slot = ch.get("kind"), ch.get("slot")
        if not isinstance(cur, str) or not isinstance(slot, str):
            continue
        seen: set[str] = set()
        while isinstance(cur, str) and cur in parents and cur not in seen:
            seen.add(cur)
            view = f"{cur}__{slot}__totality"
            if view in totality_views:
                out.add(view)
            cur = parents[cur]
    return out


def _columns_map(bundle: dict | None, rules_doc: dict | None) -> dict[str, tuple[str, ...]]:
    """Column names per relation, from the compiled schema bundle and rule IR."""
    cols: dict[str, tuple[str, ...]] = {"calc__as_of": ("id", "valid_at", "known_at")}
    if isinstance(bundle, dict):
        for k in bundle.get("kinds", []):
            if isinstance(k, dict) and isinstance(k.get("table"), str):
                cols[k["table"]] = ("id",)
        for section in ("arrows", "attributes"):
            for s in bundle.get(section, []):
                if isinstance(s, dict) and isinstance(s.get("table"), str):
                    cols[s["table"]] = ("id", "v")
        for e in bundle.get("enums", []):
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                cols[e["id"]] = ("id",)
        for r in bundle.get("relations", []):
            if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("columns"), list):
                names = tuple(c["name"] for c in r["columns"] if isinstance(c, dict) and isinstance(c.get("name"), str))
                if len(names) == len(r["columns"]):
                    cols[r["id"]] = names
    if isinstance(rules_doc, dict):
        for r in rules_doc.get("relations", []):
            if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"] not in cols:
                parts = list(r.get("key", [])) + list(r.get("values", []))
                names = tuple(c["name"] for c in parts if isinstance(c, dict) and isinstance(c.get("name"), str))
                if len(names) == len(parts):
                    cols[r["name"]] = names
        for s in rules_doc.get("seals", []):
            if isinstance(s, dict):
                if isinstance(s.get("accepted"), str):
                    cols.setdefault(s["accepted"], ("id",))
                if isinstance(s.get("row_sha256"), str):
                    cols.setdefault(s["row_sha256"], ("id", "v"))
                if isinstance(s.get("refused"), str):
                    cols.setdefault(s["refused"], ("id", "close"))
                for p in s.get("parts", []):
                    if isinstance(p, dict) and isinstance(p.get("accepted"), str):
                        cols.setdefault(p["accepted"], ("id",))
    return cols


def _row_dict(columns: dict[str, tuple[str, ...]], rel: str, key: list[str]) -> dict[str, str]:
    names = columns.get(rel)
    if names is not None and len(names) == len(key):
        return dict(zip(names, key, strict=True))
    if len(key) == 1:
        return {"v": key[0]}
    return {f"c{i}": v for i, v in enumerate(key)}


def _tree_prefix(root_uri: str, marker: str) -> str:
    key = views.key_of(root_uri)
    head, sep, _ = key.partition(f"/{marker}/")
    if not sep:
        raise ValueError(f"unexpected tree root key {key!r}")
    return head


def _walk_difference_tree(st, root: dict) -> list[dict]:
    """Read every entry of a checked `difference/<relation>` key-range tree in order."""
    prefix = _tree_prefix(root["uri"], "difference")

    def walk(key: str, digest: str) -> list[dict]:
        piece = json.loads(views._get(st, key, digest))
        if piece["level"] == 0:
            return list(piece["rows"])
        out: list[dict] = []
        for child in piece["children"]:
            out.extend(walk(f"{prefix}/{child['file']}", child["sha256"]))
        return out

    return walk(views.key_of(root["uri"]), root["sha256"])


class _TreeLookup:
    """Point lookup in checked `rezono.proof/1` key-range trees (`witness` or `sources`)."""

    def __init__(self, st, trees: dict[str, dict], marker: str):
        self.st = st
        self.trees = trees or {}
        self.marker = marker
        self._pieces: dict[str, dict] = {}

    def _load(self, key: str, digest: str) -> dict:
        if key not in self._pieces:
            self._pieces[key] = json.loads(views._get(self.st, key, digest))
        return self._pieces[key]

    def _find_leaf(self, rel: str, target: list[str]) -> tuple[str, dict] | None:
        root = self.trees.get(rel)
        if not isinstance(root, dict) or "uri" not in root or "sha256" not in root:
            return None
        prefix = _tree_prefix(root["uri"], self.marker)
        key, digest = views.key_of(root["uri"]), root["sha256"]
        while True:
            piece = self._load(key, digest)
            if piece["level"] == 0:
                return key, piece
            match = next(
                (child for child in piece["children"] if child["first"] <= target <= child["last"]),
                None,
            )
            if match is None:
                return None
            key, digest = f"{prefix}/{match['file']}", match["sha256"]

    def find_witness(self, rel: str, key_txt: str) -> str | None:
        found = self._find_leaf(rel, [key_txt])
        if found is None:
            return None
        piece_key, piece = found
        if any(w["conclusion"]["key"] == key_txt for w in piece["rows"]):
            return piece_key
        return None

    def find_source(self, rel: str, key: list[str]) -> str | None:
        found = self._find_leaf(rel, key)
        if found is None:
            return None
        piece_key, piece = found
        if any(r["key"] == key for r in piece["rows"]):
            return piece_key
        return None


class _SideProofs:
    """Checked proof and source store keys for one manifest side (`base` or assumption) and one role."""

    def __init__(self, st, manifest: dict, role: str, *, witness_trees=None, source_trees=None):
        self.st = st
        self.manifest = manifest
        self.role = role
        self.witness_trees = _TreeLookup(st, witness_trees or {}, "proof")
        self.source_trees = _TreeLookup(st, source_trees or {}, "sources")
        self.snapshot_keys = {
            s["relation"]: views.key_of(s["uri"])
            for s in manifest.get("snapshots", [])
            if s.get("role") == role
        }
        self._witness_loaded = False
        self._witness_key: str | None = None
        self._witness_refs: set[tuple[str, str]] = set()
        self._sources_loaded = False
        self._sources_key: str | None = None
        self._source_refs: set[tuple[str, str]] = set()

    def _load_witnesses(self) -> None:
        if self._witness_loaded:
            return
        self._witness_loaded = True
        entry = next((w for w in self.manifest.get("witnesses", []) if w.get("role") == self.role), None)
        if entry is None:
            return
        key = views.key_of(entry["uri"])
        doc = json.loads(views._get(self.st, key, entry["sha256"]))
        self._witness_key = key
        for section in ("witnesses", "calc_witnesses"):
            for w in doc.get(section, ()):
                c = w["conclusion"]
                self._witness_refs.add((c["relation"], c["key"]))

    def _load_sources(self) -> None:
        if self._sources_loaded:
            return
        self._sources_loaded = True
        entry = next((s for s in self.manifest.get("fact_sources", []) if s.get("role") == self.role), None)
        if entry is None:
            return
        key = views.key_of(entry["uri"])
        entries = json.loads(views._get(self.st, key, entry["sha256"]))
        self._sources_key = key
        for item in entries:
            row = item["row"]
            self._source_refs.add((row["relation"], row["key"]))

    def witness_for(self, rel: str, key: list[str]) -> str:
        key_txt = canonical_json(key)
        leaf = self.witness_trees.find_witness(rel, key_txt)
        if leaf is not None:
            return leaf
        self._load_witnesses()
        if self._witness_key is not None and (rel, key_txt) in self._witness_refs:
            return self._witness_key
        source_leaf = self.source_trees.find_source(rel, key)
        if source_leaf is not None:
            return source_leaf
        self._load_sources()
        if self._sources_key is not None and (rel, key_txt) in self._source_refs:
            return self._sources_key
        if rel in self.snapshot_keys:
            return self.snapshot_keys[rel]
        raise ValueError(f"no checked proof in store for {rel} {key_txt}")


def suppose(pack_dir, store, base_manifest: str, role: str, delta: dict) -> dict:
    """Compute a local assumption on the batch engine and return `rezono.supposition/1`.

    Copies the pack and its relative imports into a fresh work directory, applies `delta` via
    `rezono_compiler.writer.apply_delta`, publishes the assumption next to `base_manifest` as
    `p-local-<12 hex>-<epoch+1>`, runs `rezono_publisher.difference.publish` with `delta`, and
    reads back `role`'s checked difference.
    """
    from rezono_compiler import source_writer, writer

    from . import batch

    st = stores.open_store(store) if isinstance(store, str) else store
    pack_path = Path(pack_dir)
    if not isinstance(base_manifest, str) or not views.MAIN.fullmatch(base_manifest):
        raise ValueError(f"{base_manifest!r}: base_manifest must be a main manifest (m-<epoch>)")
    if not isinstance(role, str) or not role:
        raise ValueError("role must be a non-empty string")
    writer.check_delta(delta)
    try:
        proposal = proposal_name(delta)
    except CanonError as err:
        raise ValueError(f"delta is not canonical JSON: {err}") from err

    meta = yaml.safe_load((pack_path / "pack.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(meta, dict) or not isinstance(meta.get("name"), str) or not meta["name"]:
        raise ValueError(f"{pack_path / 'pack.yaml'}: missing pack name")
    pack = meta["name"]
    if delta.get("pack", pack) != pack:
        raise ValueError(f"the delta is for pack {delta['pack']!r}, not {pack!r}")

    raw_base = st.get(f"{pack}/manifests/{base_manifest}.json")
    if raw_base is None:
        raise ValueError(f"base not published: {pack}/manifests/{base_manifest}.json")
    base = json.loads(raw_base)
    if base.get("id") != base_manifest or base.get("proposal") or base.get("variant"):
        raise ValueError(f"{base_manifest}: not a main manifest")

    roles = _roles_of(base, base_manifest)
    if role not in roles:
        raise ValueError(f"role {role!r} is not published in {base_manifest}")
    if roles[role] == access.COMPLETE:
        raise ValueError(
            f"role {role!r} is published only as complete in {base_manifest} and has no reader on the server"
        )

    bundle = _compiled(st, base, "bundle/schema-bundle.json")
    rules_doc = _compiled(st, base, "ir/rules.json")
    _check_no_observations(bundle, delta)

    next_epoch = int(base["epoch"]) + 1
    knowledge_time = base["knowledge_time"]
    base_sources = [(s["source_id"], s["position"]) for s in base.get("sources", [])]
    mid = f"p-{proposal}-{next_epoch}"

    existing = st.get(f"{pack}/manifests/{mid}.json")
    if existing is not None:
        target = json.loads(existing)
        if (
            target.get("id") != mid
            or target.get("base_manifest") != base_manifest
            or target.get("proposal") != proposal
            or target.get("epoch") != next_epoch
            or target.get("knowledge_time") != knowledge_time
            or target.get("sources") != base.get("sources")
        ):
            raise ValueError(f"{mid} is published already, for another base")
        pointers.write(st, pack, "manifests", existing)
    else:
        work = writer.work_dir()
        try:
            copied = writer.checkout(pack_path, work)
            stated = source_writer.stated(proposal, _utc_instant(knowledge_time))
            texts, _ = writer.apply_delta(copied, delta, stated=stated)
            if texts:
                writer.write_files(copied, texts)
            e = batch.epoch(
                copied,
                epoch=next_epoch,
                knowledge_time=knowledge_time,
                sources=base_sources,
                proposal=proposal,
                base_manifest=base_manifest,
            )
            unset_totality = _unset_totality_checks(bundle, delta)
            if unset_totality:
                e = dataclasses.replace(
                    e,
                    checks=[
                        (c | {"status": "warning"}) if c["status"] == "red" and c["name"] in unset_totality else c
                        for c in e.checks
                    ],
                )
            target = publish.publish(e, st, roles, base=base)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    difference.publish(st, pack, mid, delta)

    explain_key = f"{pack}/{mid}/{role}/explain/index.json"
    raw_explain = st.get(explain_key)
    if raw_explain is None:
        if difference.withheld(rules_doc, bundle, delta):
            return {
                "format": FORMAT,
                "pack": pack,
                "base_manifest": base_manifest,
                "manifest": mid,
                "role": role,
                "rows": [],
                "withheld": WITHHELD_REASON,
            }
        raise ValueError(f"{explain_key}: expected difference index was not written")

    explain = json.loads(raw_explain)
    columns = _columns_map(bundle, rules_doc)

    base_views_raw = st.get(views.index_key(pack, base_manifest, role))
    base_views = json.loads(base_views_raw) if base_views_raw is not None else {}
    base_proofs = _SideProofs(
        st,
        base,
        role,
        witness_trees=(base_views.get("proof") or {}).get("trees", {}).get("witness"),
        source_trees=(base_views.get("fact_sources") or {}).get("trees"),
    )
    target_proofs = _SideProofs(
        st,
        target,
        role,
        witness_trees=(explain.get("proof") or {}).get("trees", {}).get("witness"),
    )

    rows: list[dict] = []
    diff_trees = (explain.get("difference") or {}).get("trees") or {}
    for rel in sorted(diff_trees):
        for entry in _walk_difference_tree(st, diff_trees[rel]):
            change = entry["change"]
            if change == "changed":
                old_key = entry["was"]
                new_key = entry["key"]
                rows.append({
                    "relation": rel,
                    "key": old_key,
                    "weight": -1,
                    "row": _row_dict(columns, rel, old_key),
                    "witness": base_proofs.witness_for(rel, old_key),
                })
                rows.append({
                    "relation": rel,
                    "key": new_key,
                    "weight": 1,
                    "row": _row_dict(columns, rel, new_key),
                    "witness": target_proofs.witness_for(rel, new_key),
                })
            elif change == "removed":
                old_key = entry["key"]
                rows.append({
                    "relation": rel,
                    "key": old_key,
                    "weight": -1,
                    "row": _row_dict(columns, rel, old_key),
                    "witness": base_proofs.witness_for(rel, old_key),
                })
            elif change == "added":
                new_key = entry["key"]
                rows.append({
                    "relation": rel,
                    "key": new_key,
                    "weight": 1,
                    "row": _row_dict(columns, rel, new_key),
                    "witness": target_proofs.witness_for(rel, new_key),
                })
            else:
                raise ValueError(f"{explain_key}: unknown difference change {change!r}")

    return {
        "format": FORMAT,
        "pack": pack,
        "base_manifest": base_manifest,
        "manifest": mid,
        "role": role,
        "rows": rows,
        "withheld": None,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono-suppose")
    p.add_argument("pack", help="path to the pack directory")
    p.add_argument("--profile", help="deploy profile with the section storage")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    p.add_argument("--base-manifest", required=True, help="published main manifest (m-N)")
    p.add_argument("--role", required=True, help="role published as may_read in the base manifest")
    p.add_argument("--delta", required=True, help="JSON file holding the delta (contracts/delta.yaml), or '-' for stdin")
    args = p.parse_args(argv)
    from rezono_compiler import pack as packs
    from rezono_compiler import writer

    from .__main__ import profile_settings

    url, endpoint, _ = profile_settings(args.profile) if args.profile else (None, None, {})
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    try:
        raw_delta = sys.stdin.read() if args.delta == "-" else Path(args.delta).read_text(encoding="utf-8")
        delta = json.loads(raw_delta)
        answer = suppose(args.pack, stores.open_store(url, endpoint), args.base_manifest, args.role, delta)
    except (publish.Blocked, difference.Blocked, views.Blocked) as err:
        print(f"blocked: {err}", file=sys.stderr)
        return 2
    except (stores.Conflict, ValueError, OSError, json.JSONDecodeError, writer.WriteError, packs.CompileError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(json.dumps(answer, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
