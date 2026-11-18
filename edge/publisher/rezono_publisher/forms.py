"""Each role's publication form of a main manifest, after publication
(docs/publication/l0.md, `rezono_publication.publication`).

  python -m rezono_publisher.forms PACK MANIFEST [--profile p | --store url]
  python -m rezono_publisher.forms --newest --profile p [--results FILE] [PACK_DIR ...]

The forms follow the publication (job `forms` of promote.yml, after `publish`).
`--newest` takes each pack's newest main manifest (the packs of publish.packs, or the directories given) and makes
its forms role by role: per role its objects, then its index, so a red role holds back only its own index and a
run that stopped (a timeout) goes on where it was. A role whose index is there with the role's snapshots is passed
over before anything is made. Before each role the newest main manifest is read again: when a newer one is there,
this run has been overtaken and stops for that pack (the run after the newer publication makes its forms). A
manifest whose build record differs from this run's own in anything the forms are made with (the publisher, the
checker, the compiler, a library, the runtime, a lock, the forms library: every key of `batch.build_record()` and
`forms`) is another build's: it is passed over (`foreign`), since the run that published it makes its forms, and a
form is made only by the build its manifest names. A manifest whose build names no forms library (the profile's
`forms.packs` switched the pack off when it was published) is refused. Until a role's index is written the gate
answers "no publication form yet" for it; a red run undoes no publication.

Per filtered role of the manifest (a role whose snapshots are not complete), the role's form made only from that
role's own published files (its snapshots, witnesses and fact sources, each read by the uri and sha256 the
manifest names under the role), the role-neutral schema bundle, and which relations the role reads in full
(`Snapshot.full`). Under the role's prefix:

  <pack>/<manifest>/<role>/publication/schema.json   the schema document (§2), canonical JSON
  <pack>/<manifest>/<role>/publication/rows.json     the rows as one collection {"$schema", "$rows"} (§3.1)
  <pack>/<manifest>/<role>/publication/hashes.json   every hash of §6.2, the dataset hash `d-…` among them
  <pack>/<manifest>/<role>/publication/<export>      the standards exports made from that form: view.ttl,
                                                context.jsonld, prov.ttl, shapes.ttl, contract.odcs.yaml,
                                                dcat.ttl, and the loss list of each (*.losses.yaml)
  <pack>/<manifest>/<role>/publication/table.<t>.arrow  each table of the columnar form (§4), one Arrow IPC file and
  <pack>/<manifest>/<role>/publication/table.<t>.parquet  one Parquet file per table, `$` written `_` (l0.md §4.6)
  <pack>/<manifest>/<role>/publication/statement.json  the role's epoch statement (`rezono_publication.statement`):
                                                every object above by its sha256, the role's manifest and
                                                snapshots, the dataset and annotation hash, and the row-tree
                                                roots with their inclusion hash; unsigned
  <pack>/<manifest>/<role>/publication/index.json    names each object with its sha256 and size (an export also with
                                                its loss list), the dataset and schema id and the manifest's
                                                names; written last

The complete role gets no form: its form holds what no filtered role may read, and nothing of it is written.
Each form is read back from its bytes and verified before anything is written: the library reads the schema and
the collection, the hashes are recomputed from them alone, and the rows map back onto exactly the role's own
rows, relation by relation (no element or value more or less). With `--forms` (inline), one red role and nothing
is written for any role, and the manifest is then not published either (exit 2, as the views); with `--newest`, a
red role writes no index and the other roles are written (exit 2). A form is the same bytes when made again, so a
second write is a no-op. Main manifests only.

The exports are made once, from the form as `verify` read it back from its bytes (the schema and rows a reader of
the role's prefix gets, in the order of those bytes): the exporters walk the rows and keys in the order they are
given, so they are made from what was read, never from the form in memory, which equals it but need not have its
order. `exports` is pure, so a second build from the bytes would repeat it on the same input (the tests hold that a
form and its exports are the same bytes when made again). The standards' own readers are oracles: they run in the tests
on a published store (`edge/plugins/connectors/accept.py`), never here. The tables are read back from their
own bytes, in each form: the rows they give hash to the form's hashes, and written again from those rows they are
the same bytes. The statement is made last, from the form and every object above (the tables among them), and
read back by the reader's own check (`rezono_publication.statement.verify`) from the bytes alone before anything is
written: a statement that does not say what its files say blocks every role, as a red form does.

A role's index names at most `FORM_OBJECTS` objects (the statement among them), each by a name the gate serves; the
publisher blocks above it and names the count, because the gate refuses a larger listing and the role would lose
its whole form.

A definition that L0 cannot express yet (a type the writer does not know, say) gets no form for any role:
a note on stderr, and the manifest is published as without `--forms`. That is a gap in what the publication can say,
not a wrong form; the gate then answers that the pack has no forms.

Exit 0: written (or already there, the same bytes). Exit 2: a form is not what its role's files say, nothing
written. Exit 1: an error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import PROV, RDF
from rezono_canon import canonical_json

from . import store as stores
from . import timing

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "publication") not in sys.path:
    sys.path.append(str(ROOT / "publication"))

from rezono_publication import arrow  # noqa: E402
from rezono_publication import hash as rhash  # noqa: E402
from rezono_publication import l0  # noqa: E402
from rezono_publication import publication as rd  # noqa: E402
from rezono_publication import statement as statements  # noqa: E402
from rezono_publication import rdf  # noqa: E402

FORMAT = "rezono.publication-form/1"
MAIN = re.compile(r"^m-(\d+)$")
OBJECTS = ("schema.json", "rows.json", "hashes.json")
CONNECTORS = ROOT / "edge" / "plugins" / "connectors"  # the standards exporters (docs/standards.md)
# The standards exports of a role's form, in the order they are made, each with its loss list
# (contracts/connector.yaml): the RDF view and its JSON-LD context (§5), the role's witnesses as PROV-O,
# the SHACL shapes, the ODCS contract and the DCAT entry, which names the others by addresses relative to the
# index. Each loss list is written under the same prefix, by its own name.
EXPORTS = {
    "context.jsonld": "rdf.losses.yaml",
    "view.ttl": "rdf.losses.yaml",
    "prov.ttl": "prov-o.losses.yaml",
    "shapes.ttl": "shacl.losses.yaml",
    "contract.odcs.yaml": "odcs.losses.yaml",
    "dcat.ttl": "dcat.losses.yaml",
}
# What the DCAT entry names as a distribution of the role's dataset: a form of §7 and its file.
DISTRIBUTIONS = {"row-json": "rows.json", "turtle": "view.ttl"}
OPEN = ("Q13", "Q20")  # the open questions a connector may refuse a schema for (docs/standards.md)
# The most objects a role's index may name: the bound of the listing format, written once in its description
# (edge/gate/README.md, "publication forms"); the gate holds the same number (`FORM_OBJECTS` in edge/gate/src/forms.ts)
# and each side's test reads it from there. Past half of it the design question is a listing in parts, not a higher
# number.
FORM_OBJECTS = 1024
# A name the gate serves (`NAME` in edge/gate/src/forms.ts): no path, nothing hidden.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class Blocked(Exception):
    """A role's form is not what its files say: nothing is written."""


def _sources(*parts: tuple[Path, str]) -> str:
    h = hashlib.sha256()
    for folder, pattern in parts:
        for p in sorted(folder.glob(pattern)):
            h.update(f"{p.name}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def component() -> dict:
    """What the forms are made with, for the build record: the library's source, and the exporters' source and
    loss lists. Another library or exporter is another build, so a pack is published again (`--skip-unchanged`
    compares builds)."""
    return {"format": FORMAT, "rezono_publication": _sources((ROOT / "publication" / "rezono_publication", "*.py")),
            "connectors": _sources((CONNECTORS, "*.py"), (CONNECTORS, "*.losses.yaml"))}


def _connector(name: str):
    """One exporter of `edge/plugins/connectors`: files, not a package (its README), loaded by path under a name
    of its own, so it never meets another module called `shacl` or `dcat`. Until ports run as Jobs a connector
    runs in-process."""
    key = f"rezono_connector_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, CONNECTORS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def _why_ids(rows: list[dict]) -> set[str]:
    """Every witness a form's rows name in `$why` (§3.5): a proof id, or per member of a many-valued slot."""
    out = set()
    for r in rows:
        for proof in r.get("$why", {}).values():
            out.update(proof.values() if isinstance(proof, dict) else [proof])
    return out


def exports(schema: dict, rows: list[dict], dataset: str, manifest: str, witnesses: list[dict]) -> dict[str, bytes]:
    """The standards exports of one role's form, from the form alone: its schema document, its rows, its dataset
    hash and manifest id, and the witnesses its rows name (the role's own; one the form does not name is not
    exported, one it names and the role's files lack is an error). Pure: the same form gives the same bytes.

    A connector that refuses the schema for an open question (a versioned kind, Q13; a reference into another
    pack, Q20) leaves its export out, with a note: it refuses and never guesses (docs/standards.md)."""
    pin = {"manifest": manifest, "dataset": dataset}
    shacl, odcs, dcat = _connector("shacl"), _connector("odcs"), _connector("dcat")
    by_id = {rd.witness_uri(w): w for w in witnesses}
    named = _why_ids(rows)
    if named - set(by_id):
        raise rd.FormError(f"{len(named - set(by_id))} witness(es) named in $why are not in the role's files")
    bundle = URIRef(f"{rdf.REZONO}m/{manifest}@{dataset}")

    def prov() -> str:
        g = Graph()
        g.bind("prov", PROV)
        g.bind("rd", rdf.RD)
        g.add((bundle, RDF.type, PROV.Bundle))
        for i in sorted(named):
            g += rdf.witness_to_prov(by_id[i], manifest, dataset)
        return rdf.turtle(rdf.bind_namespaces(g))  # rdflib's Turtle, in linear time

    make = {
        "context.jsonld": lambda: json.dumps(rdf.context(schema), sort_keys=True, ensure_ascii=False, indent=1),
        "view.ttl": lambda: rdf.to_turtle(schema, rows),
        "prov.ttl": prov,
        "shapes.ttl": lambda: shacl.to_turtle(schema),
        "contract.odcs.yaml": lambda: odcs.to_yaml(schema, pin),
    }
    out = {}
    for name, run in make.items():
        if _EXPORT_PHASE:
            timing.switch(_EXPORT_PHASE[-1] + name)
        try:
            out[name] = run().encode("utf-8")
        except l0.L0Error as err:
            if not any(q in str(err) for q in OPEN):
                raise
            print(f"note: {manifest}: no {name}: {err}", file=sys.stderr)  # refused, never guessed
    files = {form: f for form, f in DISTRIBUTIONS.items() if f in out or f in OBJECTS}
    if _EXPORT_PHASE:
        timing.switch(_EXPORT_PHASE[-1] + "dcat.ttl")
    out["dcat.ttl"] = dcat.to_turtle(schema, pin, files).encode("utf-8")
    return out


def losses(names) -> dict[str, bytes]:
    """The loss lists of the exports `names`, each once, as the connectors keep them."""
    return {f: (CONNECTORS / f).read_bytes() for f in sorted({EXPORTS[n] for n in names})}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_of(uri: str) -> str:
    return re.sub(r"^s3://[^/]+/", "", uri)


def prefix(pack: str, manifest: str, role: str) -> str:
    return f"{pack}/{manifest}/{role}/publication/"


def index_key(pack: str, manifest: str, role: str) -> str:
    return prefix(pack, manifest, role) + "index.json"


def _named(key: str, data: bytes | None, digest: str) -> bytes:
    if data is None:
        raise ValueError(f"{key} is not in the store")
    if sha256(data) != digest:
        raise ValueError(f"{key} does not have the sha256 that names it")
    return data


def _read(st, entries: list[dict]) -> list[bytes]:
    """Objects the manifest names, side by side, each checked against its sha256."""
    got = stores.get_all(st, [key_of(e["uri"]) for e in entries])
    return [_named(key_of(e["uri"]), data, e["sha256"]) for e, data in zip(entries, got)]


def inputs(st, m: dict, role: str, bundle: bytes) -> dict:
    """The role's own files, as the manifest names them under the role, and nothing else."""
    snaps = sorted((s for s in m["snapshots"] if s["role"] == role), key=lambda s: s["relation"])
    w = [x for x in m.get("witnesses", []) if x["role"] == role]
    s = [x for x in m.get("fact_sources") or [] if x["role"] == role]
    data = _read(st, snaps + w + s)
    rows = {e["relation"]: [tuple(x["key"]) for x in json.loads(b)] for e, b in zip(snaps, data)}
    rest = data[len(snaps):]
    return {
        "rows": rows,
        "full": {e["relation"] for e in snaps if e.get("complete") or e.get("full")},
        "witnesses": json.loads(rest[0])["witnesses"] if w else [],
        "sources": json.loads(rest[len(w)]) if s else [],
        "bundle": json.loads(bundle),
    }


def dumps(obj) -> bytes:
    """Sorted keys, no spaces: the same form gives the same bytes. Plain JSON, so a bounded integer stays a JSON
    number in row JSON (LD2); the canon would write it as text."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def objects(form: dict) -> dict[str, bytes]:
    h = form["hashes"]
    return {
        "schema.json": canonical_json(form["schema"]).encode("utf-8"),  # the bytes its id hashes (§2.5)
        "rows.json": dumps({"$schema": h["schema"], "$rows": form["rows"]}),
        "hashes.json": dumps(h),
    }


def verify(data: dict[str, bytes], form: dict, given: dict, bundle: dict, full) -> tuple[dict, dict]:
    """A form read back from its bytes alone, as a reader of the role's prefix would, and held against the role's
    own rows. Returns its hashes and what was read back (`schema`, `rows`: what the exports are made from); raises
    Blocked with what differs. The hashes were computed from the form's
    schema and rows (`rezono_publication.hash`, deterministic); the bytes must read back to exactly those, so the hashes
    follow from the bytes too without computing them a second time."""
    schema = json.loads(data["schema.json"])
    want = json.loads(data["hashes.json"])
    try:
        sid = l0.check_schema(schema)
        rows = l0.read_collection(schema, json.loads(data["rows.json"]))
    except l0.L0Error as err:
        raise Blocked(f"not a publication: {err}") from err
    if schema != form["schema"] or rows != form["rows"]:
        raise Blocked("the bytes do not read back to the form")
    if sid != want["schema"] or want != form["hashes"]:
        raise Blocked("the hashes are not those of the schema and rows")
    expected, plan = rd.schema_document(bundle, full)
    for _, (name, _cols) in sorted(plan["derived"].items()):
        if schema["kinds"].get(name) != expected["kinds"][name]:
            raise Blocked(f"{name}: its tuple_key or column types differ from the definition bundle")
    problems = rd.differences(schema, plan, rows, given)
    if problems:
        raise Blocked(f"{len(problems)} difference(s) from the role's rows (first: {'; '.join(problems[:3])})")
    return want, {"schema": schema, "rows": rows}


def verified_exports(back: dict, h: dict, manifest: str, witnesses: list[dict]) -> dict[str, bytes]:
    """The standards exports of a verified form, made once from what `verify` read back from its bytes
    (`back`): the exports of the bytes a reader fetches, in their order (the exporters follow the order of rows and
    keys). A second build would only repeat a pure function on the same input, at some 40% of the forms phase of
    the largest pack.
    The standards' own readers (pySHACL, the ODCS schema, rdflib) are oracles and run in the tests on a published
    store (`edge/plugins/connectors/accept.py`), never here."""
    try:
        return exports(back["schema"], back["rows"], h["dataset"], manifest, witnesses)
    except l0.L0Error as err:
        raise Blocked(f"standards exports: {err}") from err


def verified_tables(data: dict[str, bytes], form: dict, h: dict) -> dict[str, bytes]:
    """The columnar form of a verified form (l0.md §4): one Arrow IPC and one Parquet file per table, named
    by `arrow.file_name`. Each form's files are read back from their bytes alone, as a reader reads them, and the
    rows they give must have exactly the form's hashes (`hashes.json`); otherwise Blocked, and nothing is written.
    That they are the same bytes when written again, whatever the order of the rows, is the Arrow writer's own
    test (publication/tests/test_arrow.py), not checked here: it repeated a pure function on the same rows."""
    pin = {"dataset": h["dataset"], "manifest": form["manifest"]["id"]}
    schema = json.loads(data["schema.json"])
    try:
        made = arrow.to_files(form["schema"], form["rows"], pin)
        for f in arrow.FORMS:
            back = arrow.from_files(schema, {n: b for n, b in made.items() if n.endswith("." + f)}, f)
            if rhash.hashes(schema, back) != h:
                raise Blocked(f"the {f} tables do not hash to the form's hashes")
    except l0.L0Error as err:
        raise Blocked(f"columnar form: {err}") from err
    return made


def listable(names: list[str]) -> None:
    """What the gate requires of a role's index, held before anything is written: at most `FORM_OBJECTS` names,
    each a name it serves, none twice and never the index. Raises Blocked with the count or the name."""
    if len(names) > FORM_OBJECTS:
        raise Blocked(f"{len(names)} objects, more than the {FORM_OBJECTS} a form listing may name")
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise Blocked(f"two objects are named {twice[0]}")
    bad = [n for n in names if not NAME.match(n) or ".." in n or n == "index.json"]
    if bad:
        raise Blocked(f"{bad[0]} is not a name the gate serves")


def epoch_statement(pack: str, role: str, form: dict, h: dict, sources: list[dict], objects: dict[str, bytes]) -> bytes:
    """The role's epoch statement over its form's objects, made from the verified form and held to the
    reader's check of `rezono_publication.statement` from the bytes alone. Raises Blocked with what differs."""
    index = {"pack": pack, "role": role, "manifest": form["manifest"], "schema": h["schema"], "dataset": h["dataset"],
             "sources": sources, "objects": [{"name": n, "sha256": sha256(b)} for n, b in objects.items()]}
    try:
        data = statements.dumps(statements.make(index, objects, form["schema"], form["rows"]))
    except ValueError as err:
        raise Blocked(str(err)) from err
    index["objects"].append({"name": statements.NAME, "sha256": sha256(data)})
    problems = statements.verify(data, index, {**objects, statements.NAME: data})
    if problems:
        raise Blocked("; ".join(problems[:3]))
    return data


def load(st, pack: str, manifest: str, *, manifest_bytes: bytes | None = None) -> tuple[dict, bytes] | None:
    """The main manifest and its schema bundle; None when L0 cannot express the definition yet (a note says why)."""
    if not MAIN.match(manifest):
        raise ValueError(f"{manifest}: forms are made for main manifests (m-<epoch>) only")
    raw = manifest_bytes if manifest_bytes is not None else st.get(f"{pack}/manifests/{manifest}.json")
    if raw is None:
        raise ValueError(f"{pack}/manifests/{manifest}.json is not in the store")
    m = json.loads(raw)
    if m.get("id") != manifest or m.get("proposal") or m.get("variant"):
        raise ValueError(f"{manifest}: not a main manifest")
    if m.get("access_semantics") != 2:
        raise ValueError(f"{manifest}: not written with the access semantics of O8 (2)")
    entry = next((c for c in m.get("compiled", []) if c.get("file") == "bundle/schema-bundle.json"), None)
    if not entry:
        raise ValueError(f"{manifest}: names no compiled bundle")
    (bundle,) = _read(st, [entry])
    try:
        rd.schema_document(json.loads(bundle))  # role-neutral: can L0 express this definition at all?
    except rd.FormError as err:
        # Not a wrong form but none: the definition has what L0 does not express yet (a type, say). The
        # outcome is published without forms, and the log says why; a form that is made is always verified.
        print(f"note: {pack} {manifest}: no publication form: {err}", file=sys.stderr)
        return None
    return m, bundle


def filtered(m: dict) -> list[str]:
    """The manifest's filtered roles: those whose snapshots are not complete. The complete role gets no form."""
    return sorted({s["role"] for s in m["snapshots"] if s.get("complete") is False})


def sources_of(m: dict, role: str) -> list[dict]:
    """The role's snapshots a form is made from, as its index names them (the gate holds the index to them)."""
    return [{"relation": s["relation"], "sha256": s["sha256"]}
            for s in sorted((s for s in m["snapshots"] if s["role"] == role), key=lambda s: s["relation"])]


_EXPORT_PHASE: list[str] = []


class _phases:
    """While open, each export `exports` makes counts toward a phase of its own (`<prefix><name>`)."""

    def __init__(self, prefix: str):
        self.prefix = prefix

    def __enter__(self):
        _EXPORT_PHASE.append(self.prefix)

    def __exit__(self, *exc):
        _EXPORT_PHASE.pop()


def role_files(st, pack: str, m: dict, bundle: bytes, role: str) -> list[tuple[str, bytes]]:
    """One filtered role's form: its objects, then its index, each verified before anything is returned. Raises
    Blocked (or rd.FormError) with what is wrong. The time of each step counts toward a phase of its own
    (`<role> form`, `<role> verify`, `<role> export <name>`, `<role> tables`, `<role> statement`)."""
    manifest = m["id"]
    timing.switch(f"{role} inputs")
    given = inputs(st, m, role, bundle)
    timing.switch(f"{role} form")
    form = rd.form(m, given["bundle"], given["rows"], given["full"], given["witnesses"], given["sources"], role)
    data = objects(form)
    timing.switch(f"{role} verify")
    h, back = verify(data, form, given["rows"], given["bundle"], given["full"])
    with _phases(f"{role} export "):
        made = verified_exports(back, h, manifest, given["witnesses"])
    timing.switch(f"{role} tables")
    tables = verified_tables(data, form, h)
    names = [*OBJECTS, *made, *losses(made), *tables]
    count = len(names) + 1  # the statement is named in the index too
    print(f"forms {pack} {manifest} {role}: {count} objects of the {FORM_OBJECTS} a listing may name", file=sys.stderr)
    if count > FORM_OBJECTS // 2:
        print(f"warning: {pack} {manifest} {role}: {count} objects, more than half the {FORM_OBJECTS} a form listing "
              "may name", file=sys.stderr)
    listable([*names, statements.NAME])
    data |= made | losses(made) | tables
    base = prefix(pack, manifest, role)
    # The statement's subjects are every object of the role's form, the tables among them: made last.
    sources = sources_of(m, role)
    timing.switch(f"{role} statement")
    try:
        data[statements.NAME] = epoch_statement(pack, role, form, h, sources, {n: data[n] for n in names})
    except Blocked as err:
        raise Blocked(f"epoch statement: {err}") from err
    names.append(statements.NAME)
    index = {
        "format": FORMAT, "pack": pack, "manifest": form["manifest"], "role": role,
        "schema": h["schema"], "dataset": h["dataset"],
        # The role's snapshots it was made from, as a view index names them: the gate refuses an index that
        # was not made from exactly the role's snapshots of that manifest.
        "sources": sources,
        "objects": [{"name": n, "uri": st.uri(base + n), "sha256": sha256(data[n]), "bytes": len(data[n]),
                     **({"losses": EXPORTS[n]} if n in made else {})}
                    for n in names],
    }
    return [(base + n, data[n]) for n in names] + [(index_key(pack, manifest, role), dumps(index))]


def plan(st, pack: str, manifest: str, *, manifest_bytes: bytes | None = None) -> dict[str, list[tuple[str, bytes]]]:
    """Per filtered role, its objects with the index last. Raises Blocked if any role's form fails: with --forms
    the manifest is published only with every role's form (the deployment makes them after it, `make`)."""
    loaded = load(st, pack, manifest, manifest_bytes=manifest_bytes)
    if loaded is None:
        return {}
    m, bundle = loaded
    out, failed = {}, []
    for role in filtered(m):
        try:
            out[role] = role_files(st, pack, m, bundle, role)
        except (Blocked, rd.FormError) as err:
            failed.append(f"role {role}: publication form: {err}")
    if failed:
        raise Blocked("; ".join(failed))
    return out


def publish(st, pack: str, manifest: str, *, manifest_bytes: bytes | None = None) -> list[str]:
    """Make, verify and write every filtered role's form; each role's index after its objects. Nothing is
    written unless every role's form verifies. Returns the index keys."""
    timing.switch("forms")
    made = plan(st, pack, manifest, manifest_bytes=manifest_bytes)
    timing.switch("upload")
    for files in made.values():
        stores.put_all(st, files[:-1])
        st.put_new(*files[-1])
    return [files[-1][0] for files in made.values()]


def present(st, pack: str, m: dict, role: str) -> bool:
    """The role's form is there: its index is written (an index is written last) and names the role's snapshots."""
    data = st.get(index_key(pack, m["id"], role))
    return data is not None and json.loads(data).get("sources") == sources_of(m, role)


def build_of(st, m: dict) -> dict | None:
    """The build record the manifest names (`build`); None when it names none."""
    entry = m.get("build")
    if not entry:
        return None
    (record,) = _read(st, [entry])
    return json.loads(record)


# What a build record says that the forms are not made with: the views' layout, and the profile's roles, which the
# record of a publication holds and job `forms` does not have.
NOT_FORMS = frozenset({"views", "profile"})


def ours() -> dict:
    """This run's build in everything the forms are made with: `batch.build_record()` and the forms library."""
    from . import batch

    return batch.build_record() | {"forms": component()}


def foreign(record: dict | None, own: dict) -> list[str]:
    """The keys in which a manifest's build record differs from this run's own build (`ours`); empty when it is
    the same build. A record that names no forms library differs in `forms`."""
    record = record or {}
    return sorted(k for k in (set(record) | set(own)) - NOT_FORMS if record.get(k) != own.get(k))


class Overtaken(Exception):
    """A newer main manifest of the pack is there: the run after its publication makes its forms."""


def make(st, pack: str, m: dict, bundle: bytes) -> tuple[list[str], list[str]]:
    """The deployment's forms of one main manifest, role by role (job `forms`): a role whose form is there is
    passed over; each other role's objects are written, then its index. Before each role the newest main manifest
    is read again, and a newer one raises Overtaken. Returns (index keys written, failures); a red role writes no
    index and stops no other role."""
    from .publish import newest_main

    written, failed = [], []
    for role in filtered(m):
        timing.switch("lookup")
        newer = newest_main(st, pack)
        if newer is not None and newer["id"] != m["id"]:
            raise Overtaken(newer["id"])
        if present(st, pack, m, role):
            print(f"forms {pack} {m['id']} {role}: present", file=sys.stderr)
            continue
        try:
            files = role_files(st, pack, m, bundle, role)
        except (Blocked, rd.FormError) as err:
            failed.append(f"role {role}: publication form: {err}")
            continue
        timing.switch(f"{role} upload")
        stores.put_all(st, files[:-1])
        st.put_new(*files[-1])
        written.append(files[-1][0])
    return written, failed


def settings(profile: dict) -> tuple[int, dict[str, bool]]:
    """The profile's section `forms`: `budget_minutes` (a whole number, at least 1: the time job `forms` may take,
    whose stop is twice it) and `packs` (per pack name `on` or `off`, a YAML boolean; a pack not named is on).
    Raises ValueError on anything else."""
    s = (profile or {}).get("forms")
    if not isinstance(s, dict) or set(s) - {"budget_minutes", "packs"}:
        raise ValueError(f"forms: a section with budget_minutes and packs, not {s!r}")
    budget, packs = s.get("budget_minutes"), s.get("packs") or {}
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise ValueError(f"forms.budget_minutes must be a whole number of minutes, at least 1, not {budget!r}")
    if not isinstance(packs, dict) or not all(isinstance(k, str) and isinstance(v, bool) for k, v in packs.items()):
        raise ValueError(f"forms.packs: per pack name on or off, not {packs!r}")
    return budget, packs


def switched_on(profile: dict, pack: str) -> bool:
    """Whether the profile makes the pack's forms (`forms.packs`; on unless named off). A profile without a
    section `forms` makes every pack's."""
    return "forms" not in (profile or {}) or settings(profile)[1].get(pack, True)


def pack_name(pack_dir: str | Path) -> str | None:
    """The name pack.yaml gives the pack directory; None when it cannot be read (the compiler then says why)."""
    import yaml

    try:
        return (yaml.safe_load((Path(pack_dir) / "pack.yaml").read_text("utf-8")) or {}).get("name")
    except (OSError, AttributeError, yaml.YAMLError):
        return None


def newest(st, profile: dict, pack_dirs: list[str], root: Path, results: Path | None = None,
           own: dict | None = None) -> int:
    """`--newest`: the forms of each pack's newest main manifest. 0 every pack made, present, overtaken, foreign
    or off; 2 a red role (that role has no index; the others are written); 1 an error or a refused build. Per pack
    an outcome (`results`, a JSON object pack -> {outcome, manifest}, written again after each step, so a run that
    is stopped leaves the pack it was on as `running`). `own` is this run's build (`ours()` when not given)."""
    from .publish import newest_main

    worst, out = 0, {}
    dirs = pack_dirs or profile["publish"]["packs"]
    if not pack_dirs and "forms" in (profile or {}):
        # A name in forms.packs that is no pack of publish.packs (a typo) would leave the pack it meant on.
        unknown = sorted(set(settings(profile)[1]) - {pack_name(root / d) for d in dirs})
        if unknown:
            print(f"error: forms.packs names {unknown}, which publish.packs does not publish", file=sys.stderr)
            return 1
    own = own if own is not None else ours()

    def note(pack: str, outcome: str, manifest: str | None = None) -> None:
        out[pack] = {"outcome": outcome, **({"manifest": manifest} if manifest else {})}
        if results is not None:
            results.write_text(json.dumps(out, sort_keys=True), "utf-8")

    for pack_dir in dirs:
        pack = pack_name(root / pack_dir)
        if pack is None:
            print(f"error: {pack_dir}: no pack.yaml with a name", file=sys.stderr)
            worst = max(worst, 1)
            continue
        if not switched_on(profile, pack):
            print(f"forms {pack}: off (forms.packs of the profile)", file=sys.stderr)
            note(pack, "off")
            continue
        try:
            timing.switch("lookup")
            m = newest_main(st, pack)
            if m is None:
                print(f"forms {pack}: no main manifest", file=sys.stderr)
                note(pack, "none")
                continue
            note(pack, "running", m["id"])
            record = build_of(st, m)
            if not (record or {}).get("forms"):
                print(f"error: {pack} {m['id']}: its build names no forms library: its forms are not made",
                      file=sys.stderr)
                note(pack, "refused", m["id"])
                worst = max(worst, 1)
                continue
            differs = foreign(record, own)
            if differs:
                print(f"forms {pack} {m['id']}: another build's manifest (its build record differs in {differs}): "
                      "passed over; the run that published it makes its forms", file=sys.stderr)
                note(pack, "foreign", m["id"])
                continue
            loaded = load(st, pack, m["id"])
            if loaded is None:
                note(pack, "inexpressible", m["id"])
                continue
            written, failed = make(st, pack, *loaded)
            for key in written:
                print(key)
            if failed:
                print(f"blocked: {pack} {m['id']}: {'; '.join(failed)}", file=sys.stderr)
                note(pack, "red", m["id"])
                worst = max(worst, 2)
            else:
                note(pack, "made" if written else "present", m["id"])
        except Overtaken as newer:
            print(f"forms {pack}: overtaken by {newer}, stopped", file=sys.stderr)
            note(pack, "overtaken", str(newer))
        except Exception as err:  # noqa: BLE001 - a store's own error too (a timeout): the next pack is still tried
            print(f"error: {pack}: {type(err).__name__}: {err}", file=sys.stderr)
            note(pack, "error", out.get(pack, {}).get("manifest"))
            worst = max(worst, 1)
        finally:
            timing.report(f"{pack} forms")  # `time <pack> forms <phase> ...`: what the forms job is measured by
    return worst


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publisher.forms")
    p.add_argument("pack", nargs="?")
    p.add_argument("manifest", nargs="?")
    p.add_argument("--newest", nargs="*", metavar="PACK_DIR",
                   help="the newest main manifest of these packs, default publish.packs of the profile")
    p.add_argument("--results", help="with --newest: write each pack's outcome to this JSON file")
    p.add_argument("--profile", help="deploy profile with the section storage")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    args = p.parse_args(argv)
    from .__main__ import profile_settings

    url, endpoint, _ = profile_settings(args.profile) if args.profile else (None, None, {})
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    if args.newest is not None:
        if not args.profile or args.pack or args.manifest:
            p.error("--newest takes a profile and pack directories, not PACK MANIFEST")
        import yaml

        profile = yaml.safe_load(Path(args.profile).read_text("utf-8")) or {}
        if "forms" in profile:
            try:
                settings(profile)
            except ValueError as err:
                p.error(str(err))
        return newest(stores.open_store(url, endpoint), profile, args.newest, Path.cwd(),
                      Path(args.results) if args.results else None)
    if not (args.pack and args.manifest):
        p.error("give PACK MANIFEST, or --newest")
    try:
        for key in publish(stores.open_store(url, endpoint), args.pack, args.manifest):
            print(key)
    except Blocked as err:
        print(f"blocked: {err}", file=sys.stderr)
        return 2
    except (stores.Conflict, ValueError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
