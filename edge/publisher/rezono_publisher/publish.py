"""The publisher: after a green epoch, snapshots per role and then the manifest (contracts/manifest.yaml).

Correctness blocks: one red check and nothing is written. The epoch gives every witness instance of the
engine; a proof is chosen per role among the instances that role can read (access.py). Before
anything is written, the independent checker (checker/) checks every chosen witness of every role against
that role's snapshots, the same bytes, and that every derived row in them has exactly one witness (R7).
One error is a red check `rezono:proofs`. The manifest is written last, so a reader
never sees a manifest whose files are missing; only what a manifest lists is published. Every object is
written once (conditional put): publishing the same epoch again gives the same bytes and is a no-op.

Store layout, per pack:
  <pack>/manifests/<manifest>.json
  <pack>/heads/<10^19-1-epoch>.json   per main manifest, after it: the newest sorts first (pointers.py)
  <pack>/epochs/<epoch>/…, <pack>/bases/<base>/…   pointers to variants, diagnoses and proposals (pointers.py)
  <pack>/objects/<sha256>.json   an object keyed by the SHA-256 of its bytes, shared by roles and
                                 epochs: a role's snapshot of a relation ([{"key": [...]}, ...] sorted by key), the
                                 proofs chosen for a role (one per derived row it reads), a role's asset index (the
                                 images its image cells name, with hash, source and licence) or its source set (the
                                 sources of exactly the base rows it reads, S25, sources.py). Only the manifest says
                                 which object is what, and for which role: a reader follows its uris, never a path.
  <pack>/<manifest>/<role>/…   a role's views and publication form with their indexes, before the manifest
                               (views.py, forms.py): the gate holds them to that prefix
  <pack>/assets/<sha256>   an image, written once, shared by roles and epochs; the gate serves it
                           only to a role whose rows name it
  <pack>/bundles/<definition_sha256>/<compiler_sha256>.json   the compiled schema bundle, shared by epochs
  <pack>/bundles/<definition_sha256>/<compiler_sha256>.rules.json   the compiled rule IR
The bundle path names the pack's definition, never its facts: `pack_sha256` hashes the facts too.
An object a reference manifest names already (a variant's or a proposal's base, the newest main) is not written
again (plan): publishing an unchanged pack writes a manifest and its head only. What no retained manifest names
any more is deleted by the collector (collect.py), never by the publisher.
  <pack>/builds/<sha256>.json   what the epoch was made with (compiler, publisher, libraries, Python, lock, profile)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rezono_canon import canonical_json, sha256_hex
from rezono_checker import access as checker_access
from rezono_checker import metadata as checker_metadata
from rezono_checker import check_epoch
from rezono_checker.assets import check_role_assets
from rezono_checker.sources import check_role_sources, check_source_sets
from rezono_checker.check import shaped
from rezono_checker.rules import check_calc_bindings, derived_relations, load_rules, load_seals

from . import access, pointers, surface, timing, witness_graph
from . import sources as fact_sources
from .calc_scope import published_views
from .store import put_all

if TYPE_CHECKING:
    from .view_build import PreparedViews


class Blocked(Exception):
    """A red check: the epoch is not published."""


@dataclass(frozen=True)
class Epoch:
    """What the engine gives at the end of an epoch (engine port: views and checks out)."""

    pack: str
    epoch: int
    knowledge_time: str
    pack_sha256: str  # the whole pack, facts included: for the server side only, never for a role
    compiler_sha256: str
    schema_version: str
    engine: dict
    sources: list  # [(source_id, position)]
    checks: list  # [{"name", "status", "violations"}]
    kinds: frozenset
    rows: dict  # relation -> [tuple of canonical text]
    witnesses: list = field(default_factory=list)  # every witness instance (contracts/proof.yaml), one per θ
    proposal: str = ""
    base_manifest: str = ""
    bundle: str = ""  # the compiled schema bundle (bundle/schema-bundle.json): schema and labels, no rows
    rules: str = ""  # the compiled rule IR (ir/rules.json), if the pack has rules
    parents: dict = field(default_factory=dict)  # kind -> its parent kind (is_a), for rights on subkinds
    build: dict = field(default_factory=dict)  # what the epoch was made with (batch.build_record)
    definition_sha256: str = ""  # the pack without facts and scenarios (batch.definition_sha256)
    columns: dict = field(default_factory=dict)  # base relation -> the kind of each column, or None
    sweeps: str = ""  # the compiled sweep grid (ir/sweeps.json), if the pack has a sweep: the gate's whole grid
    variant: dict = field(default_factory=dict)  # a sweep's grid value (contracts/manifest.yaml, Variant)
    seals: tuple = ()  # the sealed kinds of the pack: the rule IR must carry each, or nothing is checked
    calc: str = ""  # the compiled calculation program (ir/calc.json), if the pack has calculation rules
    calc_witnesses: list = field(default_factory=list)  # one CalcWitness per published calculation row
    # The pack's assets/, by file: {sha256, media_type, source, licence, bytes}. Data, like facts:
    # a role gets only the files its image cells name.
    assets: dict = field(default_factory=dict)
    theory: bool = False  # source-pack metadata from the trusted epoch producer; never a public bundle field
    # The check metadata the engine loaded (rezono__*: table -> rows of canonical text). Schema, not
    # data: never a snapshot; the checker holds it against the bundle. None when the engine gave none.
    check_metadata: dict | None = None
    # the compiler's source entries of the facts (rezono_compiler.sources.read), one per base row; a
    # role gets those of its own rows. Not `sources`, which says where each source stood. None: the caller
    # supplies none (an older caller), and the manifest lists no source sets.
    fact_sources: list | None = None
    # The evidence the protected caller passed to batch.epoch (rezono_checker.evidence.Evidence), whose admitted
    # rows entered the protected relations before the rules ran (decisions/admission-transport.md). None: no
    # evidence, and the protected relations stay empty.
    evidence: object | None = None


PROOFS = "rezono:proofs"  # the check of the witnesses by the checker; not a relation name (no colon there)
SCHEMA = "rezono:schema"  # compiled schema bundle and its logical check outcomes (never synthesized downstream)
ACCESS_CHECK = "rezono:access"  # the read rules give a kind in full, and the data agrees
ACCESS_SEMANTICS = 2  # the gate refuses a manifest without it
PUBLICATION_REQUIRED = "publication_required"  # decisions/role-publication-requirements.md
ASSETS = "rezono:assets"  # the images each role gets: exactly those its image cells name
SOURCES = fact_sources.SOURCES  # the sources each role gets: exactly those of the base rows it reads


def image_tables(bundle: str) -> list[str]:
    """The slot tables the channel table binds as images (`channels.images`), sorted; none without a bundle."""
    if not bundle:
        return []
    doc = json.loads(bundle)
    table = {a["id"]: a["table"] for a in doc.get("attributes") or []}
    return sorted({table[b["slot"]] for b in (doc.get("channels") or {}).get("images") or []})


def assets_of(e: "Epoch", store, role: str, rows: dict, data: dict, tables: list[str], files: list, written: set) -> list[dict]:
    """The asset index of one role: the files its image cells name, in file order, each written once under its
    hash. Blocked when a cell names a file the pack does not list, or when the checker, which derives the named
    files itself from the bundle and `data` (the role's snapshot bytes as published), finds the index wrong."""
    named = {r[1] for t in tables for r in rows.get(t, ())}
    index, objects = [], {}
    for f in sorted(named):
        a = e.assets.get(f)
        if a is None:
            raise Blocked(f"{ASSETS}: an image cell names '{f}', which assets/sources.yaml does not list")
        key = f"{e.pack}/assets/{a['sha256']}"
        if key not in written:
            written.add(key)
            files.append((key, a["bytes"]))
        uri = store.uri(key)
        objects[uri] = a["bytes"]
        index.append({"file": f, "sha256": a["sha256"], "media_type": a["media_type"], "source": a["source"],
                      "licence": a["licence"], "uri": uri})
    errors = check_role_assets(index, e.bundle, data, objects.get)
    if errors:
        first = "; ".join(f"{x['reason']} {x['file']} {x.get('detail', '')}".strip() for x in errors[:3])
        raise Blocked(f"{ASSETS}: role {role}: {len(errors)} (first: {first})")
    return index


def sources_of(e: "Epoch", entries: dict, role: str, rows: dict, data: dict) -> bytes:
    """The bytes of one role's source-entry file: the entries of exactly the rows it reads. Blocked when the
    checker, which derives the rows itself from the bundle and the role's snapshot bytes, finds them wrong.
    The message names reasons and readable rows only: no hidden row, no count."""
    body = canonical(fact_sources.for_role(entries, rows, key_text))
    errors = check_role_sources(body, e.bundle, data)
    if errors:
        first = errors[0]
        where = " ".join([first["reason"], *(str(first[k]) for k in ("relation", "key", "field") if k in first)])
        reasons = ", ".join(sorted({x["reason"] for x in errors}))
        raise Blocked(f"{SOURCES}: role {role}: {reasons} (first: {where})")
    return body


def canonical(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode()


def key_text(row) -> str:
    return canonical_json([str(p) for p in row])


def snapshot(rows) -> bytes:
    lines = [json.dumps({"key": [str(p) for p in r]}, ensure_ascii=False, separators=(",", ":"))
             for r in sorted(set(rows), key=key_text)]
    return ("[\n" + ",\n".join(lines) + ("\n" if lines else "") + "]\n").encode()


sha256 = sha256_hex


def manifest_id(e: Epoch) -> str:
    if e.variant:
        return variant_id(e.variant["sweep"], e.variant["index"], e.epoch)
    return f"p-{e.proposal}-{e.epoch}" if e.proposal else f"m-{e.epoch}"


def variant_id(sweep: str, index: int, epoch: int) -> str:
    """v-<sweep>-<index>-<epoch>; the index has two digits, so the ids sort in grid order."""
    return f"v-{sweep}-{index:02d}-{epoch}"


def instance_pack(e: Epoch) -> None:
    """Only an ordinary pack may write an instance or its diagnosis."""
    if type(e.theory) is not bool:
        raise Blocked("the epoch's theory flag must be a boolean")
    if e.theory:
        raise Blocked("a theory pack cannot publish an instance")


def diagnose(e: Epoch, store) -> dict:
    """The diagnosis of a red variant instead of its manifest: the checks and the grid value,
    against the main manifest it varies. Nothing reads it as a state; a red variant never blocks main."""
    instance_pack(e)
    if not e.variant or not e.base_manifest:
        raise ValueError("only a variant gets a diagnosis here")
    if not any(c["status"] == "red" for c in e.checks):
        raise ValueError("a diagnosis needs a red check")
    metadata_checked(e)  # a diagnosis read with switched-off checks would under-report
    d = {"id": manifest_id(e), "epoch": e.epoch, "knowledge_time": e.knowledge_time,
         "last_good_manifest": e.base_manifest, "checks": sorted(e.checks, key=lambda c: c["name"]),
         "variant": e.variant}
    data = canonical(d)
    store.put_new(f"{e.pack}/diagnoses/{d['id']}.json", data)
    pointers.write(store, e.pack, "diagnoses", data)  # by its epoch, for the gate (pointers.py)
    return d


def frozen(e: Epoch) -> tuple[dict[str, tuple], list[dict]]:
    """A private, immutable copy of the rows and witnesses: what is checked is what is written."""
    rows = {rel: tuple(sorted({tuple(str(p) for p in r) for r in rs}, key=key_text)) for rel, rs in e.rows.items()}
    return rows, json.loads(json.dumps(e.witnesses))


def calc_ir(e: Epoch) -> dict | None:
    """The calculation program the calculation witnesses are checked against; None without one."""
    if not e.calc:
        if e.calc_witnesses:
            raise Blocked(f"{PROOFS}: calculation witnesses without ir/calc.json")
        return None
    try:
        doc = json.loads(e.calc)
    except (TypeError, ValueError) as err:
        raise Blocked(f"{PROOFS}: ir/calc.json is not JSON: {err}") from err
    if not isinstance(doc, dict) or doc.get("format") != "rezono.calc-ir/1":
        raise Blocked(f"{PROOFS}: the calculation program is not ir/calc.json (format rezono.calc-ir/1)")
    return doc


def rule_ir(e: Epoch):
    """The rule IR of the epoch: the document, the rules as the checker reads them and the derived relations.

    Rule and relation definitions are required, also for an epoch without rules (an empty rule IR): missing
    proof information never gives green.
    """
    if not e.rules:
        raise Blocked(f"{PROOFS}: no rule definitions, nothing to check the derived rows against")
    try:
        doc = json.loads(e.rules)
    except (TypeError, ValueError) as err:
        raise Blocked(f"{PROOFS}: the rule definitions are not JSON: {err}") from err
    if not isinstance(doc, dict) or doc.get("format") != "rezono.rules/1":
        # Only the compiler's rule IR has a relation catalogue; the checker's older minimal form has none.
        raise Blocked(f"{PROOFS}: the rule definitions are not the rule IR (format rezono.rules/1)")
    try:
        rules = load_rules(doc)
        derived = derived_relations(doc, rules)
    except (ValueError, KeyError, TypeError) as err:
        raise Blocked(f"{PROOFS}: the checker refuses the rule definitions: {err!r}") from err
    return doc, rules, derived


def verify(e: Epoch, snapshots=None, witnesses=None, full=None, calc_witnesses=None, role=None,
           complete=None, instances=None) -> dict:
    """The checker's report on chosen witnesses against snapshots read as complete (R7).

    Without arguments: the proofs chosen among all instances of the epoch, against its complete snapshots.
    The checker also chooses the proofs itself among all `instances` (R7) and requires the same set.
    For a filtered role (`full` given): the checker derives from the `complete` snapshots, the
    schema and the role which rows it may read and which relations it reads in full, compares that with
    its `snapshots` and `full`, and with the evidence for `full` when it carries it (`access.Full`;
    rezono_checker.access), and checks its chosen proofs against its own
    snapshots, with negation and aggregates only over the relations the checker found full.
    """
    doc, rules, derived = rule_ir(e)
    calculation = calc_ir(e)
    try:
        check_calc_bindings(doc, rules, calculation)
    except (ValueError, KeyError, TypeError) as err:
        raise Blocked(f"{PROOFS}: the checker refuses the calculation bindings: {err!r}") from err
    try:
        declared = load_seals(doc)
    except ValueError as err:
        raise Blocked(f"{PROOFS}: the checker refuses the seals of the rule IR: {err!r}") from err
    missing = sorted(set(e.seals) - {s["kind"] for s in declared})
    if missing:  # without it refused and accepted input would go unchecked
        raise Blocked(f"{PROOFS}: the rule IR has no seal for the sealed kind {', '.join(missing)}")
    seals = declared if full is None else ()  # a role's snapshots are filtered: the seal is checked whole
    scope = []
    if full is not None:
        if role is None or complete is None:
            raise ValueError("a role's proofs need the role and the complete snapshots: the checker derives its scope")
        if instances is None:
            instances = frozen(e)[1]
        try:
            bundle_doc = json.loads(e.bundle) if e.bundle else None
        except (TypeError, ValueError):
            bundle_doc = None
        full, scope = checker_access.check_role(role, complete, snapshots, full, bundle_doc,
                                                doc, calculation, instances, e.calc_witnesses, calc_witnesses or (),
                                                witnesses, claimed_evidence=getattr(full, "evidence", None))
    if snapshots is None:
        rows, instances = frozen(e)
        snapshots = {rel: snapshot(rs) for rel, rs in rows.items()}
        witnesses = sorted(access.choose(instances, derived).values(), key=access.order)
        calc_witnesses = json.loads(json.dumps(e.calc_witnesses))
    if full is None:  # R7: the complete proofs are the checker's own choice among all instances
        if instances is None:
            instances = frozen(e)[1]
        scope = checker_access.check_choice(witnesses, checker_access.select(instances, derived))
    manifest = {"id": manifest_id(e), "snapshots": [
        {"relation": rel, "role": "checker", "complete": True, "uri": rel, "sha256": sha256(b), "format": "json"}
        for rel, b in sorted(snapshots.items())]}
    report = check_epoch(witnesses, manifest, rules, snapshots.__getitem__, derived=derived, full=full, seals=seals,
                         calc_witnesses=calc_witnesses or (), calc_ir=calculation, **metadata_args(e, full),
                         evidence=e.evidence if full is None else None)  # admitted again on the complete side
    if scope:
        report = report | {"valid": False, "findings": scope + report["findings"]}  # what the filter got wrong first
    return report


def metadata_args(e: Epoch, full) -> dict:
    """What the checker needs to hold the loaded check metadata against the bundle: once, for
    the complete epoch. Only a bundle without kinds and no metadata has nothing to compare (a pack without
    kinds has no checks); anything else is compared, and a missing side is refused (fail closed)."""
    if full is not None:
        return {}
    doc = json.loads(e.bundle) if e.bundle else {}
    if not doc.get("kinds") and not e.check_metadata:
        return {}
    return {"bundle": doc, "check_metadata": e.check_metadata}


def metadata_checked(e: Epoch) -> None:
    """Blocked unless the loaded check metadata is the bundle's, for a diagnosis too."""
    args = metadata_args(e, None)
    errors = checker_metadata.check(args["bundle"], args["check_metadata"]) if args else []
    if errors:
        first = "; ".join(f"{f['reason']} {f.get('relation', '')}".strip() for f in errors[:3])
        raise Blocked(f"{PROOFS}: {len(errors)} (first: {first})")


def schema_check(e: Epoch) -> dict | None:
    """Verify the compiled schema bundle and its logical check results before emitting `rezono:schema`.

    Returns None when the epoch carries no schema bundle; otherwise requires a compiled bundle whose
    declared logical checks all appear in `e.checks` with status `"green"` (zero violations) or
    `"warning"` (propagated as a warning), never fabricating a green check.
    """
    if not e.bundle:
        if any(c.get("name") == SCHEMA for c in e.checks):
            raise Blocked(f"{SCHEMA}: caller cannot supply {SCHEMA} without a schema bundle")
        return None
    try:
        doc = json.loads(e.bundle)
    except (TypeError, ValueError) as err:
        raise Blocked(f"{SCHEMA}: the schema bundle is not JSON: {err}") from err
    if not checker_metadata.compiled(doc) or not isinstance(doc.get("checks"), list):
        raise Blocked(f"{SCHEMA}: the schema bundle is not a compiled bundle")
    by_name: dict[str, dict] = {}
    for c in e.checks:
        name = c.get("name")
        if name == SCHEMA:
            raise Blocked(f"{SCHEMA}: {SCHEMA} must be emitted by the publisher, not pre-supplied")
        if isinstance(name, str):
            if name in by_name:
                raise Blocked(f"{SCHEMA}: duplicate check result for {name}")
            by_name[name] = c
    has_warning = False
    warnings = 0
    for entry in doc["checks"]:
        view = entry.get("view") if isinstance(entry, dict) else None
        if not isinstance(view, str) or not view:
            raise Blocked(f"{SCHEMA}: malformed check declaration in schema bundle")
        result = by_name.get(view)
        if result is None:
            raise Blocked(f"{SCHEMA}: missing schema check result for {view}")
        status = result.get("status")
        violations = result.get("violations")
        if type(violations) is not int or violations < 0:
            raise Blocked(f"{SCHEMA}: {view}: invalid violations count {violations!r}")
        if status == "green":
            if violations != 0:
                raise Blocked(f"{SCHEMA}: {view}: green check has {violations} violations")
        elif status == "warning":
            has_warning = True
            warnings += violations
        else:
            raise Blocked(f"{SCHEMA}: {view}: {violations}")
    if has_warning:
        return {"name": SCHEMA, "status": "warning", "violations": warnings}
    return {"name": SCHEMA, "status": "green", "violations": 0}


def checked(e: Epoch, role: str, snapshots: dict, witnesses: list, full=None, calc_witnesses=None,
            complete=None, instances=None) -> None:
    """Blocked unless the checker finds no error in the proofs of this role."""
    with timing.phase("checker"):
        errors = [f for f in verify(e, snapshots, witnesses, full, calc_witnesses, role, complete, instances)["findings"] if f["severity"] == "error"]
    if errors:
        first = "; ".join(f"{f['reason']} {f.get('relation', '')} {f.get('key', '')}".strip() for f in errors[:3])
        raise Blocked(f"{PROOFS}: role {role}: {len(errors)} (first: {first})")


def named(*manifests: dict | None) -> set[str]:
    """The uri of every object the given manifests name: snapshots, witness, asset and source sets, compiled files,
    the build record. Each is in the store with the bytes its hash names (a manifest is written after its objects,
    and an object never changes), and stays there while the manifest is retained (collect.py)."""
    out = set()
    for m in manifests:
        if m:
            out |= {x["uri"] for s in ("snapshots", "witnesses", "assets", "fact_sources", "compiled")
                    for x in m.get(s, [])}
            if m.get("build"):
                out.add(m["build"]["uri"])
    return out


def object_key(pack: str, data: bytes) -> str:
    """Where an object of a publication is stored: under the SHA-256 of its bytes."""
    return f"{pack}/objects/{sha256(data)}.json"


ROLE_FILES = (("snapshots", "relations/{relation}.json"), ("witnesses", "witnesses.json"), ("assets", "assets.json"),
              ("fact_sources", "sources.json"))


def role_objects(store, pack: str, manifest: str, role: str) -> dict[str, str]:
    """The store keys of one role's objects in a published manifest, by what each is: `relations/<relation>.json`,
    `witnesses.json`, `assets.json`, `sources.json`. Found as every reader finds them, through the manifest's
    entries and their uris: a key says nothing of its role or its manifest. Empty without the manifest."""
    data = store.get(f"{pack}/manifests/{manifest}.json")
    if data is None:
        return {}
    m, prefix = json.loads(data), store.uri("")
    out = {}
    for section, name in ROLE_FILES:
        for x in m.get(section, []):
            if x["role"] == role and x["uri"].startswith(prefix):
                out[name.format(relation=x.get("relation"))] = x["uri"][len(prefix):]
    return dict(sorted(out.items()))


def check_publication_requirements(role: str, rows: dict, readable: dict, derived: set) -> None:
    """Check required key prefixes against both the complete and the checked role snapshots."""
    requirements = rows.get(PUBLICATION_REQUIRED, ())
    if requirements and (PUBLICATION_REQUIRED not in derived or any(len(row) != 4 for row in requirements)):
        raise Blocked(f"{PROOFS}: malformed publication requirements")
    for reader, relation, first, second in requirements:
        if reader != role:
            continue
        matching = [row for row in rows.get(relation, ()) if row[:2] == (first, second)]
        if relation not in derived or len(matching) != 1 or matching[0] not in readable.get(relation, ()):
            raise Blocked(f"{PROOFS}: role {role}: a required conclusion has no unique readable proof")


def plan(e: Epoch, store, roles: dict[str, str], base: dict | None = None,
         reuse: dict | None = None) -> tuple[list[tuple[str, bytes]], dict]:
    """Every object of the publication, in write order, and the manifest: all computed and checked before
    anything is written, from a private copy of the epoch. The manifest goes last, by the caller.

    Every snapshot, witness set, asset index and source set is keyed by the hash of its bytes (`object_key`), so
    two roles or two epochs with the same bytes name one object, and the manifest's bytes do not depend on what
    was published before. An object is written once per publication, and not at all when a reference manifest
    names it already: `base`, the published manifest `e.base_manifest` (a variant's or a proposal's main), or
    `reuse`, another retained manifest (the newest main, for a main publication). Never because "it is in the
    store": an object no retained manifest names is the collector's to delete. What is checked is unchanged: the
    checker reads the bytes, and the hash in the manifest is theirs."""
    instance_pack(e)
    if base is not None and base.get("id") != e.base_manifest:
        raise ValueError(f"the base given is {base.get('id')!r}, not the epoch's base manifest {e.base_manifest!r}")
    timing.switch("filter")  # the private copy, the proofs chosen and each role's rows (access.py)
    red = [c for c in e.checks if c["status"] == "red"]
    if red:
        raise Blocked(", ".join(f"{c['name']}: {c['violations']}" for c in red))
    schema_result = schema_check(e)
    if not roles:
        raise ValueError("no roles: nothing would be readable")
    if not e.definition_sha256:
        raise ValueError("no definition_sha256: the bundle path would have to name the facts")
    surface_error = _surface_refusal(e, store)
    if surface_error is not None:
        raise Blocked(surface_error)
    doc, _, derived = rule_ir(e)
    rows, instances = frozen(e)
    bad = [i for i, w in enumerate(instances) if not shaped(w)]
    if bad:  # never chosen from, never published: the engine gave something that is no witness
        raise Blocked(f"{PROOFS}: {len(bad)} malformed witness instances (first: {bad[0]})")
    calc_doc = calc_ir(e)
    calcs = json.loads(json.dumps(e.calc_witnesses))
    # Every relation is accounted for by a definition: a table of the schema, a relation the rule IR derives,
    # or a calculation the calculation program publishes. Anything else would go out unchecked.
    known = set(e.columns) | set(derived)
    if calc_doc is not None:
        known |= published_views(calc_doc) | {calc_doc["as_of"]}
    unknown = sorted(set(rows) - known)
    if unknown:
        raise Blocked(f"{PROOFS}: relations no definition accounts for: {', '.join(unknown[:3])}")
    complete = {rel: snapshot(rs) for rel, rs in rows.items()}
    chosen = sorted(access.choose(instances, derived).values(), key=access.order)
    checked(e, "(complete)", complete, chosen, calc_witnesses=calcs, instances=instances)
    mid = manifest_id(e)
    files, snapshots, witness_sets, asset_sets, written = [], [], [], [], set()
    source_sets, source_objects = [], {}
    there = named(base, reuse)
    entries = None
    if e.fact_sources is not None:
        try:
            entries = fact_sources.index(e.fact_sources)
            fact_sources.check_stale(entries, rows, key_text)
        except fact_sources.Stale as err:
            raise Blocked(f"{SOURCES}: {err}") from err

    def put(key: str, data: bytes) -> str:
        """The URI of `key`, holding `data`: written once, and not at all when a reference manifest names it."""
        uri = store.uri(key)
        if uri not in there and key not in written:
            written.add(key)
            files.append((key, data))
        return uri

    images = image_tables(e.bundle)
    for role in sorted(roles):
        mode = roles[role]
        if mode == access.COMPLETE:
            data = complete  # the checked bytes themselves
            sees, full = {"witnesses": chosen, "hidden": []}, frozenset(rows)
            if calc_doc is not None:
                sees["calc_witnesses"] = calcs
        elif mode == access.FILTERED:
            try:
                readable, sees, full = access.for_role(rows, e.kinds, e.parents, e.columns, doc, instances, role,
                                                       calc_doc, calcs)
            except access.Uncovered as err:
                raise Blocked(f"{ACCESS_CHECK}: {err}") from err
            data = {rel: snapshot(rs) for rel, rs in readable.items()}
            # R7, per role: its proofs against its snapshots
            checked(e, role, data, sees["witnesses"], full, calc_witnesses=sees.get("calc_witnesses"),
                    complete=complete, instances=instances)
            check_publication_requirements(role, rows, readable, derived)
        else:
            raise ValueError(f"role {role}: unknown access {mode!r}")
        for rel in sorted(data):
            uri = put(object_key(e.pack, data[rel]), data[rel])
            snapshots.append({"relation": rel, "role": role, "complete": mode == access.COMPLETE, "full": rel in full,
                              "uri": uri, "sha256": sha256(data[rel]), "format": "json"})
        sees_doc = dict(sees)
        if sees["witnesses"]:
            _, lb_rows = witness_graph.evaluate(sees["witnesses"], derived)
            lb_entries = []
            seen_prems: set[tuple[str, str, str, str, str]] = set()
            for w in sees["witnesses"]:
                c_rel, c_key = access.ref(w)
                for p in w.get("premises", ()):
                    entry = (c_rel, c_key, p["row"]["relation"], p["row"]["key"], p["polarity"])
                    if entry not in seen_prems:
                        seen_prems.add(entry)
                        lb_entries.append((entry, entry in lb_rows))
            lb_entries.sort(key=lambda item: item[0])
            sees_doc["load_bearing_entries"] = [
                {
                    "conclusion": {"relation": c_rel, "key": c_key},
                    "premise": {"relation": p_rel, "key": p_key},
                    "how": how,
                    "load_bearing": bool(flag),
                }
                for (c_rel, c_key, p_rel, p_key, how), flag in lb_entries
            ]
        body = canonical(sees_doc)
        uri = put(object_key(e.pack, body), body)
        witness_sets.append({"role": role, "uri": uri, "sha256": sha256(body)})
        if images:  # only the images this role's own rows name
            pictures: list = []
            index = assets_of(e, store, role, rows if mode == access.COMPLETE else readable, data, images, pictures,
                              set())
            body = canonical(index)
            key = object_key(e.pack, body)
            if store.uri(key) not in there:  # an index written now: its images too, before it (each once)
                for k, b in pictures:  # a reference's index is retained with every image it names
                    put(k, b)
            uri = put(key, body)
            asset_sets.append({"role": role, "uri": uri, "sha256": sha256(body)})
        if entries is not None:  # the sources of the rows this role reads, checked before anything is written
            body = sources_of(e, entries, role, rows if mode == access.COMPLETE else readable, data)
            uri = put(object_key(e.pack, body), body)
            source_objects[uri] = body
            source_sets.append({"role": role, "uri": uri, "sha256": sha256(body)})
    if entries is not None:
        errors = check_source_sets(source_sets, roles, source_objects.get)
        if errors:
            raise Blocked(f"{SOURCES}: the source sets: {', '.join(sorted({x['reason'] for x in errors}))}")
    # What was compiled, archived with its hash, so a publication can be made again and compared byte
    # for byte: the bundle (where the gate reads it), the rule IR next to it (the one the proofs were
    # checked against), and a sweep's grid (the gate shows a grid value without a variant as not computed).
    compiled = []
    for file, text, suffix in (("bundle/schema-bundle.json", e.bundle, ".json"),
                              ("ir/rules.json", e.rules, ".rules.json"),
                              ("ir/calc.json", e.calc, ".calc.json"),
                              ("ir/sweeps.json", e.sweeps, ".sweeps.json")):
        if text:
            key = f"{e.pack}/bundles/{e.definition_sha256}/{e.compiler_sha256}{suffix}"
            uri = put(key, text.encode())
            compiled.append({"file": file, "uri": uri, "sha256": sha256(text.encode())})
    # The build record with the effective profile: what to set up again to make this publication again.
    build = None
    if e.build:
        data = build_bytes(e.build, roles)
        uri = put(f"{e.pack}/builds/{sha256(data)}.json", data)
        build = {"file": "build.json", "uri": uri, "sha256": sha256(data)}
    manifest = {
        "id": mid,
        "epoch": e.epoch,
        "knowledge_time": e.knowledge_time,
        "access_semantics": ACCESS_SEMANTICS,
        "pack_sha256": e.pack_sha256,
        "definition_sha256": e.definition_sha256,
        "compiler_sha256": e.compiler_sha256,
        "engine": dict(e.engine),
        "schema_version": e.schema_version,
        "sources": [{"source_id": s, "position": p} for s, p in sorted(e.sources)],
        "checks": sorted([*(dict(c) for c in e.checks), {"name": PROOFS, "status": "green", "violations": 0},
                          *([schema_result] if schema_result is not None else []),
                          *([{"name": ASSETS, "status": "green", "violations": 0}] if images else []),
                          *([{"name": SOURCES, "status": "green", "violations": 0}] if entries is not None else [])],
                         key=lambda c: c["name"]),
        "counts": [{"relation": rel, "rows": len(rs)} for rel, rs in sorted(rows.items())],
        "snapshots": snapshots,
        "witnesses": witness_sets,
    }
    if asset_sets:
        manifest["assets"] = asset_sets
    if entries is not None:
        manifest["fact_sources"] = source_sets
    if compiled:
        manifest["compiled"] = compiled
    if build:
        manifest["build"] = build
    if e.base_manifest:
        manifest["base_manifest"] = e.base_manifest
    if e.proposal:
        manifest["proposal"] = e.proposal
    if e.variant:
        manifest["variant"] = e.variant
    manifest |= candidates(e)
    return files, manifest


def candidates(e: Epoch) -> dict:
    """The candidate references the epoch's admission step read from the submitted index, for the complete
    manifest (decisions/admission-transport.md, section 2): `completeness_receipts` and `rounds`, each only when
    it lists one. The trusted context confers the authority and its bytes are never published; `evidence` names it
    and the submitted index by hash, so a later replay of the publication rebuilds the Evidence and admits again
    (retained_calculation). The access gate gives a role's manifest none of these."""
    if e.evidence is None:
        return {}
    from rezono_checker import evidence as admission

    try:
        references = admission.admit(e.evidence).references
    except ValueError as err:
        raise Blocked(f"rezono:evidence: {err}") from err
    named = {"context": e.evidence.context}
    if e.evidence.candidates is not None:
        named["index"] = e.evidence.candidates
    return {field: references[field] for field in admission.INDEX_FIELDS if references[field]} | {"evidence": named}


def build_bytes(build: dict, roles: dict[str, str]) -> bytes:
    """The build record as it is published: what the epoch was made with, and the effective profile."""
    return canonical(build | {"profile": {"roles": dict(sorted(roles.items()))}})


def newest_main(store, pack: str) -> dict | None:
    """The newest main manifest of the pack, found as the gate finds it: the first key under `<pack>/heads/`
    (pointers.py), then the manifest by its key. None without a head. A head that is not the head of the
    manifest it names, byte for byte, is an error: nothing is concluded from it."""
    keys = sorted(k for k in store.list(f"{pack}/heads/") if k.endswith(".json"))
    if not keys:
        return None
    body = store.get(keys[0])
    try:
        name = json.loads(body)["manifest"]
        data = store.get(f"{pack}/manifests/{name}.json")
        if data is None or pointers.head(pack, data) != (keys[0], body):
            raise ValueError("it names another manifest, or none")
        return json.loads(data)
    except (TypeError, KeyError, ValueError) as err:
        raise ValueError(f"{keys[0]} is not a head: {err}") from err


def _surface_refusal(e: Epoch, store) -> str | None:
    """Check public-surface compatibility for a main publication before anything is written
    (decisions/language-surface-compatibility.md, sections 2 and 4).

    Skipped for proposals, variants and epochs with a base manifest, and only for bundle-less
    synthetic epochs on minimal test stores that do not expose `list()`. Any real store (or any
    epoch with a bundle) fails closed on a broken head, missing or mismatched bundle, malformed
    semver, unaccepted major change (R033), or insufficient pack version bump.
    """
    if e.proposal or e.variant or e.base_manifest:
        return None
    if not e.bundle and not hasattr(store, "list"):
        return None
    previous = newest_main(store, e.pack)
    if previous is None:
        return None
    return surface.refusal(e, store, previous)


def compatibility(e: Epoch, store) -> dict | None:
    """Classify the public-surface change of a main epoch against the newest main manifest
    (decisions/language-surface-compatibility.md, section 2).

    Returns None for a proposal, a variant, an epoch with a base manifest, a pack without an earlier
    main manifest, or an epoch whose definition_sha256 and compiler_sha256 match the newest main
    manifest. Otherwise returns {"against": <manifest id>, "class": ..., "changes": [...]}, reading
    the earlier bundle through its compiled entry uri and holding it to its sha256.
    """
    if e.proposal or e.variant or e.base_manifest:
        return None
    previous = newest_main(store, e.pack)
    if previous is None:
        return None
    return surface.compatibility(e, store, previous)


def unchanged(head: dict | None, *, pack_sha256: str, engine: dict, build: dict, roles: dict[str, str]) -> bool:
    """True when the main manifest `head` was made from exactly what a new epoch would be made from now:
    the same pack, every file of it, facts included (its imports are pinned in its pack.yaml); the
    same engine; and the same build record (the compiler, the checker, the publisher, every library, the
    runtime, the lock, the views' code and the profile's roles). The same input gives the same bytes (AGENTS.md
    rule 3), so the new epoch would give every role the rows, proofs and views it has; only the epoch, the
    knowledge time and the commit it names would differ. Anything missing counts as a change: when in doubt,
    the epoch is computed and checked as always."""
    if not head or not build or not pack_sha256:
        return False
    made = head.get("build")
    return (head.get("pack_sha256") == pack_sha256 and head.get("engine") == dict(engine)
            and isinstance(made, dict) and made.get("sha256") == sha256(build_bytes(build, roles)))


def publish(e: Epoch, store, roles: dict[str, str], base: dict | None = None, *,
            reuse: dict | None = None, prepared_views: PreparedViews | None = None, forms: bool = False) -> dict:
    """Publish one epoch for the given roles ({role: "complete" | "may_read"}). Returns the manifest. With
    `base` (the published base manifest) or `reuse` (a retained manifest, the newest main), only what neither
    names already is written (plan).
    With prepared main views, write their checked indexes before exposing the manifest; with `forms`, each
    filtered role's publication form too (forms.py), verified before anything of it is written."""
    files, manifest = plan(e, store, roles, base, reuse)
    data = canonical(manifest)  # fixed before the first write
    timing.switch("upload")
    put_all(store, files)  # concurrently; the manifest only after every file is there
    if prepared_views is not None:
        from . import views
        views.publish(store, e.pack, manifest["id"], prepared=prepared_views, manifest_bytes=data)
    if forms:
        from . import forms as publication_forms
        publication_forms.publish(store, e.pack, manifest["id"], manifest_bytes=data)
    timing.switch("manifest")
    store.put_new(f"{e.pack}/manifests/{manifest['id']}.json", data)
    # Its head (main) or pointer (variant, proposal), right after it: the gate finds it by key (pointers.py).
    pointers.write(store, e.pack, "manifests", data)
    return json.loads(data)
