"""Sweep v1 (docs/interaction.md, section 1): after main's manifest m-N, one epoch per grid value of the pack's
sweep, each published as a variant against m-N.

  python -m rezono_publisher.sweep PACK --profile deploy/profiles/edge.yaml (--base-commit <sha> | --newest) \
      [--repo .] [--store file:///data] [--workers N]

With --workers N, N processes compute the variants side by side, each a share of the grid (side_by_side;
sweep.sh asks for two). The store then holds what one process writes: a variant's bytes depend on its base
and its value alone. A variant of the lab is 13 s of computation, so its 64 are 13 minutes one after
another, whatever is written.

With --newest the base is the pack's newest main manifest, at the commit it names: what publish.sh left as
main, also when it found the pack unchanged and published nothing for HEAD.

- The grid comes from the compiler (`sweeps.yaml` and the slot's `explore`). Each value is one delta `set` on
  main's facts at the base commit, in a private work dir (git worktree), in grid order. The epoch is N + 1, the
  knowledge time and the source those of m-N, as for a proposal.
- A green value becomes the variant manifest `<pack>/manifests/v-<sweep>-<ii>-<N+1>.json` with base_manifest
  m-N. A red value (a red check) becomes the diagnosis `<pack>/diagnoses/v-<sweep>-<ii>-<N+1>.json`. A red
  variant never blocks main: m-N is published before the first variant is computed.
- Any other error (a crash, a checker failure, a conflict in the store) stops the run with exit 1.
- A variant that is there already is kept, so a run that stopped (a timeout) is completed by the next one.
  A kept variant whose differences are there too costs a lookup: nothing is made or written again.
  A variant that is not there is "not computed": never red, never green.
- Each variant writes only what differs from m-N (publish.plan with `base`): every other snapshot, witness set
  and compiled file of a variant is m-N's own object for the same role, with the same bytes. So a variant
  costs the objects the swept cell changes, not a whole publication (measured on the lab: 30 of 516).
- Roles: `readers` may read the swept cell; only they get the variant. `status_readers` also
  read every row, so a variant's status tells them nothing they cannot see; the others see `unavailable`.
  The gate removes both lists before it serves a variant.

Exit 0: every variant is there (one line per variant: id and what happened). Exit 1: an error.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

from rezono_canon import canonical_json
from rezono_checker import access as checker_access
from rezono_checker import turns as checker_turns
from rezono_checker.check import shaped

from . import access, difference, pointers, publish, store, timing, turns, views
from .cache import SweepStore
from .__main__ import profile_settings
from .proposal import COMMIT, base_of, git, pack_name, same_source

TURNS_FORMAT = "rezono.turns/1"


def grid(sweep: dict) -> list[int]:
    return [sweep["min"] + i * sweep["step"] for i in range(sweep["count"])]


def roles_of(e: publish.Epoch, roles: dict[str, str], kind: str, key: str) -> tuple[list[str], list[str]]:
    """Who gets the variant and who sees its status, with the access semantics of a publication (O7, O8).

    A reader may read the swept element (kind, key). A status reader has coverage of every relation,
    so whether a role sees the status tells nothing about a row it may not read. Every other reader sees
    `unavailable` (the gate does that).
    """
    doc = json.loads(e.rules)
    columns = access.with_calc(e.columns, publish.calc_ir(e))  # as a publication sees them
    readers, status_readers = [], []
    for role, mode in sorted(roles.items()):
        if mode == access.COMPLETE:
            readers.append(role)
            status_readers.append(role)
            continue
        if mode != access.FILTERED:
            raise ValueError(f"role {role}: unknown access {mode!r}")
        try:
            scope = access.Scope(e.rows, e.kinds, e.parents, columns, doc, role, e.witnesses)
        except access.Uncovered as err:
            raise publish.Blocked(f"{publish.ACCESS_CHECK}: {err}") from err
        if not scope.reads(kind, key):
            continue
        readers.append(role)
        if scope.full >= set(e.rows):
            status_readers.append(role)
    return readers, status_readers


def verify_status_readers(e: publish.Epoch, roles: dict[str, str], variant: dict) -> None:
    """Verify variant `status_readers` through the independent checker before writing a manifest or diagnosis."""
    if not isinstance(roles, Mapping):
        raise publish.Blocked(f"{publish.ACCESS_CHECK}: malformed roles")
    complete_roles = frozenset(role for role, mode in roles.items() if mode == access.COMPLETE)
    role_full: dict[str, frozenset[str]] = {}
    raw_status = variant.get("status_readers", ()) if isinstance(variant, Mapping) else ()
    filtered_status = (
        sorted({r for r in raw_status if isinstance(r, str) and r and roles.get(r) == access.FILTERED})
        if isinstance(raw_status, (list, tuple))
        else []
    )
    all_relations = frozenset(e.rows)
    if filtered_status:
        doc, _, _ = publish.rule_ir(e)
        rows, instances = publish.frozen(e)
        bad = [i for i, w in enumerate(instances) if not shaped(w)]
        if bad:
            raise publish.Blocked(f"{publish.PROOFS}: {len(bad)} malformed witness instances (first: {bad[0]})")
        calc_doc = publish.calc_ir(e)
        calcs = json.loads(json.dumps(e.calc_witnesses))
        try:
            bundle_doc = json.loads(e.bundle) if e.bundle else None
        except (TypeError, ValueError):
            bundle_doc = None
        complete = {rel: publish.snapshot(rs) for rel, rs in rows.items()}
        all_relations = frozenset(rows)
        for role in filtered_status:
            try:
                readable, sees, claimed_full = access.for_role(
                    rows, e.kinds, e.parents, e.columns, doc, instances, role, calc_doc, calcs
                )
            except access.Uncovered as err:
                raise publish.Blocked(f"{publish.ACCESS_CHECK}: {err}") from err
            role_snaps = {rel: publish.snapshot(rs) for rel, rs in readable.items()}
            derived_full, role_findings = checker_access.check_role(
                role, complete, role_snaps, claimed_full, bundle_doc,
                doc, calc_doc, instances, calcs, sees.get("calc_witnesses") or (),
                sees["witnesses"], claimed_evidence=getattr(claimed_full, "evidence", None),
            )
            role_errors = [f for f in role_findings if f.get("severity") == "error"]
            if role_errors:
                first = "; ".join(f"{f['reason']} {f.get('relation', '')}".strip() for f in role_errors[:3])
                raise publish.Blocked(f"{publish.PROOFS}: role {role}: {len(role_errors)} (first: {first})")
            role_full[role] = derived_full
    findings = checker_access.check_variant_status_readers(
        variant, role_full, all_relations, complete_roles=complete_roles
    )
    errors = [f for f in findings if f.get("severity") == "error"]
    if errors:
        first = "; ".join(f"{f['reason']} {f.get('role', '')}".strip() for f in errors[:3])
        raise publish.Blocked(f"{publish.ACCESS_CHECK}: variant status_readers: {len(errors)} (first: {first})")


def change_of(sw: dict) -> dict:
    """The change a variant makes, without its value: what decides whether a right may change (difference.withheld)."""
    return {"op": "set", "kind": sw["kind"], "key": sw["key"], "slot": sw["slot"]}


def kept(st, pack: str, vid: str, base: str) -> str | None:
    """'manifest' or 'diagnosis' if the variant is there already, for the same base; None if not."""
    for what, kind, field in (("manifest", "manifests", "base_manifest"), ("diagnosis", "diagnoses", "last_good_manifest")):
        data = st.get(f"{pack}/{kind}/{vid}.json")
        if data is not None:
            if json.loads(data).get(field) != base:
                raise ValueError(f"{vid} is there already, for another base")
            # A run that stopped between the object and its pointer: the pointer from the kept bytes.
            pointers.write(st, pack, kind, data)
            return what
    return None


def explained(st, pack: str, vid: str, main: dict) -> bool:
    """True when the differences of a kept variant are all there: the index of every role the gate serves in
    the variant and in its base (the roles of difference.plan). The indexes are written after every piece of
    every role (difference.publish), so together they say the pieces are there; a run that stopped anywhere
    before them finds one missing and makes the differences again. False also where there is no index to
    find (no such role, or a delta that may change a right): making nothing again costs little."""
    m = json.loads(st.get(f"{pack}/manifests/{vid}.json"))
    served = {s["role"] for s in m["snapshots"] if s.get("complete") is False}
    served &= {s["role"] for s in main["snapshots"] if s.get("complete") is False}
    return bool(served) and all(st.get(f"{pack}/{vid}/{role}/explain/index.json") is not None
                                for role in sorted(served))


def _io(st, before):
    return " ".join(f"{k}={v - before[k]}" for k, v in st.counts().items())


@contextmanager
def _phase(st, label, name):
    start = time.monotonic()
    before = st.counts()
    print(f"sweep {label} {name} start", file=sys.stderr, flush=True)
    try:
        yield
    finally:
        print(f"sweep {label} {name} {time.monotonic() - start:.3f}s {_io(st, before)}",
              file=sys.stderr, flush=True)


def _difference(st, name, vid, change, label):
    with _phase(st, label, "difference"):
        difference.publish(st, name, vid, {"changes": [change]})


def turns_key(pack: str, after_manifest: str, role: str) -> str:
    """Store key of one role's turning-point object for a pair ending at `after_manifest`."""
    return f"{pack}/{after_manifest}/{role}/turns.json"


def _slot_column_type(semantic: object, raw_type: object) -> str:
    if isinstance(semantic, dict):
        case = semantic.get("case")
        base = semantic.get("base")
        if case == "ref":
            return "reference"
        if case == "enum":
            return "enum"
        if case == "date" or base == "date":
            return "date"
        if base == "boolean":
            return "boolean"
        if base in ("integer", "number") or case in ("money", "quantity"):
            return "number"
    if raw_type == "enum":
        return "enum"
    if raw_type == "boolean":
        return "boolean"
    if raw_type == "date":
        return "date"
    if raw_type in ("integer", "rational", "number"):
        return "number"
    return "text"


def _columns_of(bundle: dict | None, rules_doc: dict | None, calc_doc: dict | None) -> dict[str, list[str]]:
    columns: dict[str, list[str]] = {}
    calc_rule_types: dict[str, str] = {}
    if isinstance(calc_doc, dict):
        for rule in calc_doc.get("rules") or ():
            if isinstance(rule, dict) and isinstance(rule.get("rule"), str) and isinstance(rule.get("type"), str):
                calc_rule_types[rule["rule"]] = rule["type"]
    if isinstance(bundle, dict):
        for kind in bundle.get("kinds") or ():
            if isinstance(kind, dict) and isinstance(kind.get("table"), str):
                columns[kind["table"]] = ["reference"]
        for arrow in bundle.get("arrows") or ():
            if isinstance(arrow, dict) and isinstance(arrow.get("table"), str):
                columns[arrow["table"]] = ["reference", "reference"]
        for attr in bundle.get("attributes") or ():
            if isinstance(attr, dict) and isinstance(attr.get("table"), str):
                columns[attr["table"]] = ["reference", _slot_column_type(attr.get("semantic"), attr.get("type"))]
        for rel in bundle.get("relations") or ():
            if not isinstance(rel, dict) or not isinstance(rel.get("id"), str):
                continue
            calc_ref = rel.get("calc")
            if isinstance(calc_ref, str) and calc_ref:
                rule_name = calc_ref.split("@", 1)[0]
                sem = rel.get("semantic")
                if isinstance(sem, dict) and sem.get("base") == "boolean":
                    val_type = "boolean"
                elif calc_rule_types.get(rule_name) == "boolean":
                    val_type = "boolean"
                else:
                    val_type = "number"
                columns[rel["id"]] = ["reference", val_type, "enum", "text"]
            else:
                cols = rel.get("columns") or ()
                columns[rel["id"]] = [
                    _slot_column_type(col.get("semantic"), col.get("type"))
                    for col in cols if isinstance(col, dict)
                ]
    if isinstance(calc_doc, dict):
        for rule in calc_doc.get("rules") or ():
            if isinstance(rule, dict) and isinstance(rule.get("view"), str) and rule["view"] not in columns:
                val_type = "boolean" if rule.get("type") == "boolean" else "number"
                columns[rule["view"]] = ["reference", val_type, "enum", "text"]
        for ver in calc_doc.get("versions") or ():
            if isinstance(ver, dict) and isinstance(ver.get("view"), str) and ver["view"] not in columns:
                val_type = "boolean" if calc_rule_types.get(ver.get("rule", "")) == "boolean" else "number"
                columns[ver["view"]] = ["reference", val_type, "enum", "text"]
    if isinstance(rules_doc, dict):
        for rel in rules_doc.get("relations") or ():
            if isinstance(rel, dict) and isinstance(rel.get("name"), str) and rel["name"] not in columns:
                columns[rel["name"]] = [
                    _slot_column_type(None, col.get("type"))
                    for col in rel.get("key") or () if isinstance(col, dict)
                ]
    return columns


def _compiled_json(st, manifest: dict, file: str) -> dict | None:
    entry = next((c for c in manifest.get("compiled") or () if isinstance(c, dict) and c.get("file") == file), None)
    if entry is None:
        return None
    return json.loads(views._get(st, views.key_of(entry["uri"]), entry["sha256"]))


def _stop_data(st, manifest: dict, role: str) -> dict:
    """Read one role's own snapshots and witness set from a verified variant manifest."""
    snaps = sorted(
        (s for s in manifest.get("snapshots") or () if isinstance(s, dict) and s.get("role") == role),
        key=lambda s: s["relation"],
    )
    raw_snaps = views._snapshots(st, snaps)
    rows = {rel: [canonical_json(r["key"]) for r in json.loads(data)] for rel, data in raw_snaps.items()}
    wref = next((w for w in manifest.get("witnesses") or () if isinstance(w, dict) and w.get("role") == role), None)
    if wref is not None:
        sees = json.loads(views._get(st, views.key_of(wref["uri"]), wref["sha256"]))
        witnesses = sees.get("witnesses") or []
        calc_witnesses = sees.get("calc_witnesses") or []
    else:
        witnesses, calc_witnesses = [], []
    return {"rows": rows, "witnesses": witnesses, "calc_witnesses": calc_witnesses}


def _turns_roles(before_m: dict, after_m: dict) -> list[str]:
    """Roles that see the status and snapshots of both stops (decisions/viewer-slip.md, Turning points)."""
    def status_set(manifest: dict) -> set[str]:
        variant = manifest.get("variant")
        if not isinstance(variant, dict):
            return set()
        readers = variant.get("readers")
        status_readers = variant.get("status_readers")
        if (not isinstance(readers, list) or not isinstance(status_readers, list)
                or not all(isinstance(r, str) and r for r in readers)
                or not all(isinstance(r, str) and r for r in status_readers)):
            return set()
        rset = set(readers)
        sset = set(status_readers)
        if not sset <= rset:
            return set()
        snap_roles = {s["role"] for s in manifest.get("snapshots") or () if isinstance(s, dict) and isinstance(s.get("role"), str)}
        return sset & snap_roles

    return sorted(status_set(before_m) & status_set(after_m))


def publish_turns(st, pack: str, base: str, sweep_name: str, before_index: int, after_index: int,
                  epoch: int) -> list[str]:
    """Build, independently check, and store one `rezono.turns/1` object per status-reading role for a pair
    of neighbouring variant stops that both exist in `st`. Returns the store keys written."""
    if after_index != before_index + 1 or before_index < 0:
        raise ValueError(f"turns pair must be neighbouring indices, not ({before_index}, {after_index})")
    before_vid = publish.variant_id(sweep_name, before_index, epoch)
    after_vid = publish.variant_id(sweep_name, after_index, epoch)
    before_raw = st.get(f"{pack}/manifests/{before_vid}.json")
    after_raw = st.get(f"{pack}/manifests/{after_vid}.json")
    if before_raw is None or after_raw is None:
        return []
    before_m = json.loads(before_raw)
    after_m = json.loads(after_raw)
    if (before_m.get("id") != before_vid or after_m.get("id") != after_vid
            or before_m.get("base_manifest") != base or after_m.get("base_manifest") != base):
        return []
    before_v, after_v = before_m.get("variant"), after_m.get("variant")
    if (not isinstance(before_v, dict) or not isinstance(after_v, dict)
            or before_v.get("sweep") != sweep_name or after_v.get("sweep") != sweep_name
            or before_v.get("index") != before_index or after_v.get("index") != after_index):
        return []
    pair_roles = _turns_roles(before_m, after_m)
    missing_roles = [role for role in pair_roles if st.get(turns_key(pack, after_vid, role)) is None]
    if not missing_roles:
        return []
    bundle = _compiled_json(st, after_m, "bundle/schema-bundle.json")
    rules_doc = _compiled_json(st, after_m, "ir/rules.json")
    calc_doc = _compiled_json(st, after_m, "ir/calc.json")
    columns = _columns_of(bundle, rules_doc, calc_doc)
    before_sha = publish.sha256(before_raw)
    after_sha = publish.sha256(after_raw)
    files: list[tuple[str, bytes]] = []
    for role in missing_roles:
        before_stop = _stop_data(st, before_m, role)
        after_stop = _stop_data(st, after_m, role)
        listed = turns.between(columns, calc_doc, before_stop, after_stop)
        with timing.phase("checker"):
            problems = checker_turns.check(columns, calc_doc, before_stop, after_stop, listed)
        if problems:
            raise publish.Blocked(
                f"{publish.PROOFS}: role {role}: turns {before_vid}->{after_vid}: "
                f"{len(problems)} (first: {'; '.join(problems[:3])})"
            )
        doc = {
            "format": TURNS_FORMAT,
            "pack": pack,
            "role": role,
            "sweep": sweep_name,
            "base_manifest": base,
            "before": {"index": before_index, "manifest": before_vid, "sha256": before_sha},
            "after": {"index": after_index, "manifest": after_vid, "sha256": after_sha},
            "turns": listed,
        }
        files.append((turns_key(pack, after_vid, role), views.dumps(doc)))
    store.put_all(st, files)
    return [key for key, _ in files]


def _neighbor_turns(st, pack: str, base: str, sweep_name: str, index: int, count: int, epoch: int, label: str) -> None:
    with _phase(st, label, "turns"):
        if index > 0:
            publish_turns(st, pack, base, sweep_name, index - 1, index, epoch)
        if index + 1 < count:
            publish_turns(st, pack, base, sweep_name, index, index + 1, epoch)


def newest_commit(repo: Path, pack: str, st) -> str:
    """The commit of the pack's newest main manifest (its `rules` source): the base of `--newest`."""
    head = publish.newest_main(st, pack_name(repo / pack))
    if head is None:
        raise ValueError(f"base not published: {pack} has no main manifest")
    sources = {s.get("source_id"): s.get("position") for s in head.get("sources", []) if isinstance(s, dict)}
    commit = sources.get("rules")
    if not isinstance(commit, str) or not COMMIT.match(commit):
        raise ValueError(f"the newest main manifest {head.get('id')} names no commit as its rules")
    return commit


# glibc's malloc serves a block of this size or more with its own mmap, returned to the system when freed.
# Its default threshold is dynamic: each freed mmapped block raises it (up to 32 MiB), so later blocks of
# that size come from the heap, where a variant's freed blocks stay as fragments. The pilot's workers grew by
# about 30 MiB per variant on Linux. A lab worker's live heap stays at 91 MiB over 16 variants while malloc's
# free memory grows from 235 to 396 MiB (resident 607 -> 756 MiB); with the threshold fixed at glibc's
# initial 128 KiB the free memory stays at 82-85 MiB (resident 489 -> 540 MiB) and the run is no slower
# (16-11-2026). Other platforms ignore the variable.
MALLOC_ENV = {"MALLOC_MMAP_THRESHOLD_": str(128 * 1024)}


def side_by_side(argv: list[str], workers: int) -> tuple[int, list[str]]:
    """The sweep `argv` names, by `workers` processes at once: (exit code, the lines of all, by variant id).

    Worker i takes the grid values whose index is i modulo `workers` (`--part`), in a work dir and with a
    cache of its own. A variant is a function of its base and its value, it writes only keys of its own, and
    every object is written once (store.put_new). So the store holds afterwards what one process writes,
    whatever the number of workers and the order they end in. The base is the caller's, one for all: a worker
    never looks up the newest main manifest itself. A worker's malloc returns what a variant freed
    (MALLOC_ENV), unless the caller set the variable itself."""
    env = MALLOC_ENV | dict(os.environ)
    children = [subprocess.Popen([sys.executable, "-m", "rezono_publisher.sweep", *argv, "--part", f"{i}/{workers}"],
                                 stdout=subprocess.PIPE, text=True, env=env) for i in range(workers)]
    lines = [line for child in children for line in child.communicate()[0].splitlines()]
    return (1 if any(child.returncode for child in children) else 0), sorted(lines)


def _file_rows(pack, data: dict) -> Counter[tuple[str, str]]:
    """Canonical base rows emitted by one fact file's parsed mapping."""
    from rezono_compiler import facts as compiler_facts

    out: Counter[tuple[str, str]] = Counter()
    judged = compiler_facts.schema(pack)

    def on_row(table, values, *_):
        out[(table, canonical_json(values))] += 1

    for kind, records in data.items():
        for record in records or []:
            compiler_facts.walk(judged, kind, record, on_row=on_row)
    return out


def _swept_cell_rows(lay, data: dict, change: dict) -> Counter[tuple[str, str]]:
    """Canonical base rows contributed by the swept cell `(kind, key, slot)`."""
    from rezono_compiler import facts as compiler_facts
    from rezono_compiler import writer

    kind = change["kind"]
    slot = change["slot"]
    ident, id_type = lay.identifier(kind)
    key = writer.scalar(id_type, change["key"], f"{kind}.{ident}")
    records = [r for r in data.get(kind) or [] if writer.same(r.get(ident), key)]
    if not records:
        return Counter()
    out: Counter[tuple[str, str]] = Counter()

    def on_row(table, values, row_kind, row_key, row_slot, _):
        if row_kind == kind and row_key == key and row_slot == slot:
            out[(table, canonical_json(values))] += 1

    compiler_facts.walk(compiler_facts.schema(lay.pack), kind, records[0], on_row=on_row)
    return out


def _preserved_origin(entries: list[dict], refs: list[tuple[str, str]], where: str) -> dict:
    """Collect the existing base sources (and optional reason) of `refs` without inventing any origin."""
    from rezono_compiler import writer

    by_ref = {(e["row"]["relation"], e["row"]["key"]): e for e in entries}
    selected = [by_ref[ref] for ref in refs if ref in by_ref]
    if not selected:
        raise writer.WriteError(f"{where}: base fact row has no source entry to preserve")
    sources_map = {canonical_json(s): s for e in selected for s in e["sources"]}
    reasons = {e["reason"] for e in selected if "reason" in e}
    if len(reasons) > 1:
        raise writer.WriteError(f"{where}: conflicting source reasons on swept cell")
    preserved: dict = {"sources": [sources_map[k] for k in sorted(sources_map, key=lambda s: s.encode("utf-16-be"))]}
    if reasons:
        preserved["reason"] = next(iter(reasons))
    return preserved


def _sweep_texts(pack_dir: Path, lay, change: dict) -> dict[str, str]:
    """Apply one sweep `set` change to its fact file while preserving the swept cell's base origins.

    A sweep varies an existing cell to explore consequences; it never stamps `synthetic` onto the
    swept cell or hides an uncited / self-citing cell (decisions/fact-origin-required.md §§1-3, 5).
    """
    import yaml
    from rezono_compiler import facts as compiler_facts
    from rezono_compiler import source_format, source_writer, strict_yaml, writer
    from rezono_compiler import sources as provenance

    rel = writer.locate(pack_dir, lay, change["kind"], change["key"], {})
    old_text = writer.read_fact_file(pack_dir, rel)
    new_text, _ = source_format.of(rel).edit_fact(lay, old_text, change)
    texts = {rel: new_text}

    comp = source_writer.companion(rel)
    comp_path = writer.fact_path(pack_dir, comp)
    if not comp_path.exists():
        return texts

    try:
        old_comp = comp_path.read_bytes().decode("utf-8")
        doc = strict_yaml.load(old_comp, comp)
        old_data = strict_yaml.load(old_text, rel) or {}
        new_data = strict_yaml.load(new_text, rel) or {}
        base_entries = provenance.text_entries(lay.pack, rel, old_text, old_data, metadata=doc)
    except (compiler_facts.LoadError, yaml.YAMLError, UnicodeDecodeError) as err:
        raise writer.WriteError(f"{comp}: {err}") from err

    if new_text == old_text:
        texts[comp] = old_comp
        return texts

    before_rows = _file_rows(lay.pack, old_data)
    after_rows = _file_rows(lay.pack, new_data)
    before = _swept_cell_rows(lay, old_data, change)
    after = _swept_cell_rows(lay, new_data, change)
    if not after:
        raise writer.WriteError(f"{rel}: swept cell produced no row")
    if any(before_rows[r] > before[r] for r in before) or any(after_rows[r] > after[r] for r in after):
        raise writer.WriteError(f"{rel}: ambiguous shared-row source contribution")

    ledger = {(e["row"]["relation"], e["row"]["key"]): e for e in base_entries}
    if before:
        origin = _preserved_origin(
            base_entries, sorted(before), f"{rel} ({change['kind']} {change['key']}.{change['slot']})"
        )
    else:
        ident, id_type = lay.identifier(change["kind"])
        key = writer.scalar(id_type, change["key"], f"{change['kind']}.{ident}")
        key_json = canonical_json([key])
        rec_refs = [ref for a in lay.pack.ancestors(change["kind"]) if (ref := (a, key_json)) in ledger][:1]
        origin = _preserved_origin(base_entries, rec_refs, f"{rel} ({change['kind']} {change['key']})")

    for ref in before:
        ledger.pop(ref, None)
    for rel_name, key_str in sorted(after):
        ledger[(rel_name, key_str)] = {"row": {"relation": rel_name, "key": key_str}, **origin}
    if set(ledger) != set(after_rows):
        raise writer.WriteError(f"{rel}: unexplained source loss or new fact")

    try:
        texts[comp] = provenance.canonical_sidecar_text(lay.pack, rel, new_text, list(ledger.values()))
    except compiler_facts.LoadError as err:
        raise writer.WriteError(f"{comp}: {err}") from err
    return texts


def run(repo: Path, pack: str, base_commit: str, st, roles: dict[str, str],
        part: tuple[int, int] = (0, 1)) -> list[tuple[str, str]]:
    """The variants of the pack's sweeps against the main manifest of `base_commit`: [(variant id, what
    happened)]. `part` (i, n): only the grid values whose index is i modulo n (side_by_side)."""
    from rezono_compiler import pack as packs
    from rezono_compiler import writer

    from . import batch

    if not COMMIT.match(base_commit):
        raise ValueError("the base commit is 40 lower-case hex digits")
    if not roles:
        raise ValueError("no roles: nothing would be readable")
    n, knowledge_time = base_of(repo, base_commit)
    base = f"m-{n}"
    work = Path(tempfile.mkdtemp(prefix=writer.WORK_PREFIX))
    done = []
    try:
        git(repo, "worktree", "add", "-q", "--detach", str(work / "repo"), base_commit)
        pack_dir = work / "repo" / pack
        if (work / "repo").resolve() not in pack_dir.resolve().parents:
            raise ValueError(f"the pack must be a directory inside the repository, not {pack!r}")
        model = packs.read(pack_dir)
        name = model.meta["name"]
        st = SweepStore(st, name, base)
        published = st.get(f"{name}/manifests/{base}.json")
        if published is None:
            raise ValueError(f"base not published: {name}/manifests/{base}.json")
        main = json.loads(published)
        if not same_source(main, base, n, base_commit):
            raise ValueError(f"the published {base} is not of commit {base_commit}: another commit with as many ancestors")
        lay = None
        for sw in model.sweeps:
            values = grid(sw)
            for i, value in enumerate(values):
                if i % part[1] != part[0]:
                    continue  # another worker's value
                vid = publish.variant_id(sw["name"], i, n + 1)
                label = f"{pack}/{vid}"
                before = st.begin(vid)
                print(f"sweep {label} start", file=sys.stderr, flush=True)
                timing.switch("lookup")
                result = "error"
                try:
                    with _phase(st, label, "lookup"):
                        there = kept(st, name, vid, base)
                    if there:
                        # A run that stopped before the difference: made again, the same bytes. One that is
                        # whole costs its lookup, so a sweep with nothing to compute writes nothing.
                        if there == "manifest" and not explained(st, name, vid, main):
                            _difference(st, name, vid, change_of(sw), label)
                        if there == "manifest":
                            _neighbor_turns(st, name, base, sw["name"], i, len(values), n + 1, label)
                        result = f"{there} kept"
                    else:
                        change = {"op": "set", "kind": sw["kind"], "key": sw["key"], "slot": sw["slot"], "value": value}
                        if lay is None:
                            lay = writer.layout(pack_dir)
                        texts = _sweep_texts(pack_dir, lay, change)
                        originals = {f: writer.read_fact_file(pack_dir, f) for f in texts}
                        writer.write_files(pack_dir, texts)
                        try:
                            with _phase(st, label, "epoch"):
                                e = batch.epoch(pack_dir, epoch=n + 1, knowledge_time=knowledge_time,
                                                sources=[("rules", base_commit)], base_manifest=base)
                        finally:
                            writer.write_files(pack_dir, originals)  # the next value starts from main's facts again
                        readers, status_readers = roles_of(e, roles, sw["kind"], sw["key"])
                        variant = {"sweep": sw["name"], "index": i, "value": str(value),
                                   "readers": readers, "status_readers": status_readers}
                        verify_status_readers(e, roles, variant)
                        e = dataclasses.replace(e, variant=variant)
                        if any(c["status"] == "red" for c in e.checks):
                            publish.diagnose(e, st)
                            result = "diagnosis"
                        else:
                            with _phase(st, label, "publication"):
                                publish.publish(e, st, {r: roles[r] for r in readers}, base=main)
                            _difference(st, name, vid, change, label)
                            _neighbor_turns(st, name, base, sw["name"], i, len(values), n + 1, label)
                            result = "manifest"
                    done.append((vid, result))
                finally:
                    timing.report(label, out=sys.stderr)
                    print(f"sweep {label} {result} {_io(st, before)}", file=sys.stderr, flush=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(work / "repo")], cwd=repo, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m rezono_publisher.sweep")
    p.add_argument("pack")
    p.add_argument("--profile", required=True)
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    base = p.add_mutually_exclusive_group(required=True)
    base.add_argument("--base-commit", help="the commit of the main manifest the variants vary")
    base.add_argument("--newest", action="store_true",
                      help="vary the pack's newest main manifest, at the commit it names")
    p.add_argument("--repo", default=".")
    p.add_argument("--workers", type=int, default=1, help="variants side by side: this many processes")
    p.add_argument("--part", default="0/1", help=argparse.SUPPRESS)  # I/N: a worker's share of the grid
    args = p.parse_args(argv)
    from rezono_compiler import writer

    url, endpoint, roles = profile_settings(args.profile)
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    part = tuple(int(x) for x in args.part.split("/"))
    if args.workers < 1 or len(part) != 2 or not 0 <= part[0] < part[1]:
        p.error("--workers is 1 or more, and --part is I/N with 0 <= I < N")
    try:
        repo, st = Path(args.repo).resolve(), store.open_store(url, endpoint)
        commit = args.base_commit or newest_commit(repo, args.pack, st)
        if args.workers > 1:
            code, lines = side_by_side([args.pack, "--profile", args.profile, "--base-commit", commit, "--repo",
                                        str(repo), *(["--store", args.store] if args.store else [])], args.workers)
            for line in lines:
                print(line)
            return code
        done = run(repo, args.pack, commit, st, roles, part)
    except (publish.Blocked, difference.Blocked, store.Conflict, ValueError, writer.WriteError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    for vid, what in done:
        print(vid, what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
