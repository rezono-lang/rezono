"""The RDF view of the publication (docs/publication/l0.md §5): the published context, the converter, PROV-O.

- `context(schema)`: the JSON-LD 1.1 context published at `<base>s-<hex>/context.jsonld`: protected, with a
  type-scoped context per kind, so one slot name on two kinds expands to two IRIs (X01).
- `expand(schema, document)`: JSON-LD processing of a document under that context, to an `rdflib.Graph`. An
  embedded context that redefines a term of the published one is refused (X02): rdflib 7.6 does not raise the
  JSON-LD error `protected term redefinition` itself, so this module checks it before rdflib reads the document.
- `to_graph(schema, rows)` and `from_graph(schema, graph)`: the publication converter, the full view without loss
  (T03): element IRIs (§3.4), states as blank nodes, `rd:emptySet` for `[]`, `rd:world rd:closed` on a closed
  kind, `$why` and `$src` as statement annotations. `to_turtle`/`from_turtle` and `to_jsonld`/`from_jsonld` are
  the same converter through text.
- `witness_to_prov(witness, manifest, dataset)` and `prov_to_witness(graph)`: a witness as PROV-O: the
  conclusion a `prov:Entity`, the rule application a `prov:Activity`, the premises `prov:used`, the epoch a
  `prov:Bundle`. What PROV-O has no term for travels as `rd:` terms; `PROV_LOSS` lists it.

rdflib parses and writes; the meaning is this module's. RDF 1.2 triple terms are not in rdflib 7.6, so an
annotation is an `rdf:Statement` (the fallback §5 allows). How a versioned element maps to nodes is open (Q13):
the converter refuses a versioned kind rather than choose. A reference into another pack is refused too: its IRI
needs the other pack's `base`, which the schema's import does not carry (Q20).
"""

import hashlib
import io
import json
import re

import rdflib
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import PROV, RDF, RDFS, XSD, split_uri
from rdflib.plugins.serializers.turtle import TurtleSerializer
from rdflib.term import _is_valid_uri

from rezono_canon import CanonError, canonical_json, canonical_sha256

from . import hash as rhash
from . import l0

# `<ns>/publication/1.0#` (§7); `<ns>` is still open (Q1). A profile URI is an identifier, not a fetch target.
RD = Namespace("https://rezono.org/publication/1.0#")
REZONO = "rezono:"  # Rezono's own names: `rezono:w/<hash>` a witness, `rezono:r/<relation>/<key>` a row, `rezono:m/…` an epoch
_STATE_TERMS = {"unknown": RD.unknown, "not_applicable": RD.notApplicable, "invalid": RD.invalid}
_STATE_KEY = {"unknown": "$unknown", "not_applicable": "$na", "invalid": "$invalid"}
_XSD = {"Text": XSD.string, "Bool": XSD.boolean, "Integer": XSD.integer, "Date": XSD.date, "DateTime": XSD.dateTime}
PROV_LOSS = (
    "rd:absent: a negative premise (PROV-O has no absence)",
    "rd:polarity, rd:stratum and rd:position on each prov:Usage",
    "rd:rule: the rule id (no PROV-O term names a rule)",
    "rd:binding: the substitution of the rule variables",
    "rd:aggregate: aggregate evidence, as the canonical JSON of each aggregate",
)


class RdfError(l0.L0Error):
    """RDF input that the publication does not accept, or a row the converter cannot write."""


def _fail(where: str, what: str):
    raise RdfError(f"{where}: {what}")


def _bnode(*parts) -> BNode:
    """A blank node labelled by what it stands for, never by chance: the serializer orders blank nodes by label,
    so the same rows give the same Turtle bytes (the publisher writes the view and checks it made again)."""
    text = "\0".join(p.n3() if hasattr(p, "n3") else str(p) for p in parts)
    return BNode("b" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32])


def bind_namespaces(g: Graph) -> Graph:
    """Name every namespace of a predicate in `g` that has no prefix yet, `n1`, `n2`, … in the code-point order of
    the namespaces. Left to rdflib, an unbound namespace is named in the order the serializer meets the triples,
    which follows Python's string hashing, so the Turtle would change from one process to the next."""
    bound = {str(ns) for _, ns in g.namespace_manager.namespaces()}
    spaces = set()
    for p in set(g.predicates()):
        try:
            spaces.add(split_uri(str(p))[0])
        except ValueError:
            continue  # no local name to split off: the serializer writes the full IRI
    for i, ns in enumerate(sorted(spaces - bound), 1):
        g.bind(f"n{i}", Namespace(ns), override=False)
    return g


# ---------------------------------------------------------------------------------------------------------------
# IRIs


def schema_iri(schema: dict) -> str:
    """`<base>s-<hex>/`: where the context, the shapes and the local types of this schema are published (§5)."""
    return f"{schema['base']}{l0.schema_id(schema)}/"


def kind_iri(schema: dict, kind: str) -> str:
    """The kind's `iri`, else its `map` entry, else `<base><Kind>` (§2.1)."""
    k = schema["kinds"][kind]
    return k.get("iri") or schema.get("map", {}).get(kind) or f"{schema['base']}{kind}"


def slot_iri(schema: dict, kind: str, slot: str) -> str:
    """`<kind iri>#<slot>`, or the slot's `map` entry (§5), of the kind that declares the slot: a slot a subkind
    restates is the same property (§2.1 `parent`)."""
    kind = l0.declaring(schema, kind, slot)
    return schema.get("map", {}).get(f"{kind}.{slot}") or f"{kind_iri(schema, kind)}#{slot}"


_PLAIN = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._")
_HEX = frozenset("0123456789ABCDEF")


def spell(text: str) -> str:
    """An id as one IRI segment (§3.4): letters, digits, `-`, `.` and `_` as they are, every other character,
    `~` included, as `~` and two upper-case hex digits per byte of its UTF-8 form. Only these characters pass a
    redirecting resolver unchanged (docs/ring2/iris.md §4.1). `.` and `..` write their dots as `~2E`: a client
    removes a dot segment before it sends the request."""
    if text in (".", ".."):
        return "~2E" * len(text)
    return "".join(c if c in _PLAIN else "".join(f"~{b:02X}" for b in c.encode("utf-8")) for c in text)


def unspell(segment: str) -> str:
    """The id a segment spells. One way only: a segment that is not the spelling of its id is refused, so an id
    has exactly one IRI."""
    out, i = bytearray(), 0
    while i < len(segment):
        c = segment[i]
        if c == "~":
            pair = segment[i + 1:i + 3]
            if len(pair) != 2 or not set(pair) <= _HEX:
                _fail(segment, "a `~` is followed by two upper-case hex digits (§3.4)")
            out.append(int(pair, 16))
            i += 3
        elif c in _PLAIN:
            out.append(ord(c))
            i += 1
        else:
            _fail(segment, f"`{c}` is not written as itself in an IRI segment (§3.4)")
    try:
        text = out.decode("utf-8")
    except UnicodeDecodeError:
        _fail(segment, "not the UTF-8 form of a text (§3.4)")
    if spell(text) != segment:
        _fail(segment, "not the spelling of its id (§3.4)")
    return text


def element_space(schema: dict, kind: str) -> str:
    """Where a kind's elements live: the `iri` of the root of its tree, else `<base><Root>` (§2.1, §3.4). An
    element of a subkind is an element of its parent, so the whole tree shares one space and an element has one
    IRI, whatever kind a reference names it by. Never a `map` entry: that names another vocabulary's term, and
    an element is not one of its names."""
    kind = l0.root(schema, kind)
    return schema["kinds"][kind].get("iri") or f"{schema['base']}{kind}"


def element_iri(schema: dict, kind: str, rid: str) -> str:
    """`<kind iri>/<spelled id>` (§3.4)."""
    return f"{element_space(schema, kind)}/{spell(rid)}"


_PIN_VALUE = re.compile(r"(?:(?P<manifest>m-[0-9]+)@)?(?P<dataset>d-[0-9a-f]{64})")
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _snake(name: str) -> str:
    """PascalCase kind name -> snake_case relation name."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def pin_iri(iri: str, *, dataset: str, manifest: str | None = None) -> str:
    """Pin a canonical IRI to a dataset hash (`?pin=d-<64 hex>`) or epoch and hash (`?pin=m-<epoch>@d-<64 hex>`)."""
    if isinstance(iri, URIRef):
        iri = str(iri)
    if not isinstance(iri, str) or not l0._IRI.fullmatch(iri):
        _fail("iri", "an IRI to pin must be an absolute IRI")
    if "?" in iri or "#" in iri:
        _fail(iri, "cannot pin an IRI that already carries `?` or `#`")
    if manifest is not None and dataset is None:
        _fail("pin", "epoch pin without hash pin: `manifest` needs `dataset` `d-<64 hex>` (§6.4)")
    if not isinstance(dataset, str) or not l0._DID.fullmatch(dataset):
        _fail("pin", "hash pin must be `d-<64 hex>` (§6.4)")
    if manifest is not None:
        if not isinstance(manifest, str) or not l0._MID.fullmatch(manifest):
            _fail("pin", "epoch pin must be `m-<epoch>` (§6.4)")
        return f"{iri}?pin={manifest}@{dataset}"
    return f"{iri}?pin={dataset}"


def parse_pin(iri: str) -> tuple[str, dict[str, str] | None]:
    """Split an optional `?pin=` query parameter from a canonical IRI (§6.4)."""
    if isinstance(iri, URIRef):
        iri = str(iri)
    if not isinstance(iri, str) or not l0._IRI.fullmatch(iri):
        _fail(str(iri), "must be an absolute IRI")
    if "#" in iri:
        _fail(iri, "fragments are not allowed in a canonical or pinned IRI")
    if "?" not in iri:
        return iri, None
    base, query = iri.split("?", 1)
    if "?" in query or not base or not l0._IRI.fullmatch(base):
        _fail(iri, "malformed query in IRI")
    if "&" in query or not query.startswith("pin="):
        _fail(iri, "only the `pin` query parameter is allowed")
    raw = query[4:]
    if l0._MID.fullmatch(raw):
        _fail(iri, "epoch pin without hash pin: `m-<epoch>` requires `@d-<64 hex>` (§6.4)")
    match = _PIN_VALUE.fullmatch(raw)
    if not match:
        _fail(iri, "malformed pin: expected `d-<64 hex>` or `m-<epoch>@d-<64 hex>` (§6.4)")
    if match.group("manifest") is not None:
        return base, {"manifest": match.group("manifest"), "dataset": match.group("dataset")}
    return base, {"dataset": match.group("dataset")}


def conclusion_iri(schema: dict, kind: str, row_id: str, *, manifest: str | None = None,
                   dataset: str | None = None) -> str:
    """Canonical conclusion IRI `<kind iri>/<spelled id>` (optionally pinned via `?pin=`)."""
    l0.check_schema(schema)
    if not isinstance(kind, str) or kind not in schema["kinds"]:
        _fail(str(kind), "not a kind of this schema")
    if not isinstance(row_id, str) or not row_id:
        _fail("row_id", "row id must be non-empty text")
    iri = element_iri(schema, kind, row_id)
    if dataset is not None or manifest is not None:
        return pin_iri(iri, dataset=dataset, manifest=manifest)
    return iri


def canonical_witness_iri(schema: dict, witness: dict, *, manifest: str | None = None,
                          dataset: str | None = None) -> str:
    """Canonical witness IRI `<base>witness/<H(witness)>` (optionally pinned via `?pin=`)."""
    l0.check_schema(schema)
    try:
        digest = canonical_sha256(witness)
    except CanonError as err:
        _fail("witness", str(err))
    iri = f"{schema['base']}witness/{digest}"
    if dataset is not None or manifest is not None:
        return pin_iri(iri, dataset=dataset, manifest=manifest)
    return iri


def _schema_relation_maps(schema: dict, *, include_subkinds: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Bijective relation <-> kind maps for `schema`."""
    candidates = [
        name for name, spec in schema["kinds"].items()
        if include_subkinds or "parent" not in spec
    ]
    counts: dict[str, int] = {}
    for name in candidates:
        rel = _snake(name)
        counts[rel] = counts.get(rel, 0) + 1
    rel_to_kind = {_snake(name): name for name in candidates if counts[_snake(name)] == 1}
    kind_to_rel = {name: rel for rel, name in rel_to_kind.items()}
    return rel_to_kind, kind_to_rel


def _ref_to_kind_id(schema: dict, ref: dict, *, include_subkinds: bool = False) -> tuple[str, str] | None:
    """Map a witness `RowRef` (`{"relation", "key"}`) to `(kind, row_id)` under `schema`, or None if outside it."""
    if not isinstance(ref, dict):
        return None
    relation, key = ref.get("relation"), ref.get("key")
    if not isinstance(relation, str) or not isinstance(key, str) or not key:
        return None
    rel_to_kind, _ = _schema_relation_maps(schema, include_subkinds=include_subkinds)
    kind = rel_to_kind.get(relation)
    if kind is None:
        return None
    if "tuple_key" in schema["kinds"][kind]:
        return kind, key
    try:
        parts = json.loads(key)
    except json.JSONDecodeError:
        return None
    if not (isinstance(parts, list) and len(parts) == 1 and isinstance(parts[0], str) and parts[0]):
        return None
    if canonical_json(parts) != key:
        return None
    return kind, parts[0]


def resolve_iri(schema: dict, rows: list, iri: str, *, witnesses=(), manifest: str | None = None,
                dataset: str | None = None) -> dict:
    """Resolve a canonical conclusion IRI or canonical witness IRI (pinned or unpinned) to exactly one row."""
    l0.check_schema(schema)
    checked = l0.read_rows(schema, rows)
    unpinned, pin = parse_pin(iri)
    if pin is not None:
        expected_dataset = rhash.hashes(schema, checked)["dataset"] if dataset is None else dataset
        if not isinstance(expected_dataset, str) or not l0._DID.fullmatch(expected_dataset):
            _fail("dataset", "dataset hash must be `d-<64 hex>` (§6.4)")
        if pin["dataset"] != expected_dataset:
            _fail(iri, f"dataset pin `{pin['dataset']}` does not match `{expected_dataset}`")
        if "manifest" in pin:
            if manifest is None:
                _fail(iri, f"manifest pin `{pin['manifest']}` requires `manifest` to be supplied")
            if not isinstance(manifest, str) or not l0._MID.fullmatch(manifest):
                _fail("manifest", "manifest id must be `m-<epoch>` (§6.4)")
            if manifest != pin["manifest"]:
                _fail(iri, f"manifest pin `{pin['manifest']}` does not match `{manifest}`")

    witness_prefix = f"{schema['base']}witness/"
    if unpinned.startswith(witness_prefix):
        digest = unpinned[len(witness_prefix):]
        if not _HEX64.fullmatch(digest):
            _fail(iri, "witness IRI must end with a 64-character lower-case hex digest")
        matched_witness = None
        for witness in witnesses:
            try:
                if canonical_sha256(witness) == digest:
                    matched_witness = witness
                    break
            except CanonError as err:
                _fail("witness", str(err))
        if matched_witness is None:
            _fail(iri, f"no witness with digest `{digest}`")
        conclusion = matched_witness.get("conclusion") if isinstance(matched_witness, dict) else None
        if not isinstance(conclusion, dict):
            _fail(iri, "witness has no `conclusion` RowRef")
        mapped = _ref_to_kind_id(schema, conclusion, include_subkinds=True)
        if mapped is None:
            _fail(iri, f"witness conclusion {conclusion!r} does not map to a kind of this schema")
        kind, row_id = mapped
        target_root = l0.root(schema, kind)
        matches = [
            row for row in checked
            if row["$id"] == row_id
            and kind in l0.chain(schema, row["$kind"])
            and l0.root(schema, row["$kind"]) == target_root
        ]
        if len(matches) != 1:
            _fail(iri, f"witness conclusion resolved to {len(matches)} rows, expected 1")
        row = matches[0]
        why_id = row.get("$why", {}).get("$id")
        if why_id is not None and why_id != unpinned:
            _fail(iri, f"row `$why.$id` `{why_id}` does not match witness IRI `{unpinned}`")
        return row

    space, sep, segment = unpinned.rpartition("/")
    if not sep or not segment:
        _fail(iri, "not a canonical conclusion or witness IRI of this schema")
    space_to_root = {
        element_space(schema, name): name
        for name, spec in schema["kinds"].items()
        if "parent" not in spec
    }
    root_kind = space_to_root.get(space)
    if root_kind is None:
        _fail(iri, "does not match any kind space of this schema")
    row_id = unspell(segment)
    matches = [
        row for row in checked
        if l0.root(schema, row["$kind"]) == root_kind and row["$id"] == row_id
    ]
    if len(matches) != 1:
        _fail(iri, f"IRI resolved to {len(matches)} rows, expected 1")
    return matches[0]


def _type_iri(schema: dict, name: str) -> str:
    return str(_XSD[name]) if name in _XSD else f"{schema_iri(schema)}types/{name}"


# ---------------------------------------------------------------------------------------------------------------
# §5: the published context, and JSON-LD processing under it


def context(schema: dict) -> dict:
    """The context document `{"@context": …}` published for the schema (§5)."""
    l0.check_schema(schema)
    top = {
        "@version": 1.1, "@protected": True, "rd": str(RD),
        "$id": "@id", "$ref": "@id", "$kind": "@type", "$rows": "@graph",
        "$unknown": "rd:unknown", "$na": "rd:notApplicable", "$invalid": "rd:invalid",
        "$valid": "rd:valid", "$known": "rd:known", "$schema": None, "$why": None, "$src": None,
    }
    for name, kind in sorted(schema["kinds"].items()):
        scoped = {}
        for slot_name, slot in sorted(kind["slots"].items()):
            term = {"@id": slot_iri(schema, name, slot_name)}
            term["@type"] = "@id" if "ref" in slot else _type_iri(schema, slot["type"])
            scoped[slot_name] = term
        top[name] = {"@id": kind_iri(schema, name), "@context": scoped}
    return {"@context": top}


def _defined_terms(ctx: dict) -> dict:
    """Every term the published context defines, top level and kind-scoped, with its definition."""
    terms = {}
    for term, definition in ctx.items():
        if term.startswith("@"):
            continue
        terms[term] = definition
        if isinstance(definition, dict):
            for inner, d in definition.get("@context", {}).items():
                terms.setdefault(f"{term}/{inner}", d)
                terms.setdefault(inner, None)  # a slot name: defined in some kind's scope
    return terms


def expand(schema: dict, document) -> Graph:
    """JSON-LD processing of a publication document under the published context; returns its triples.

    The document names the context by its URL (`<base>s-<hex>/context.jsonld`), which is resolved here and never
    fetched. A protected term redefined in an embedded context is a processing error (X02).
    """
    url = schema_iri(schema) + "context.jsonld"
    published = context(schema)["@context"]
    terms = _defined_terms(published)

    def resolve(ctx):
        if ctx == url:
            return published
        if isinstance(ctx, list):
            return [resolve(c) for c in ctx]
        return ctx

    def check(value, where):
        if isinstance(value, list):
            for i, v in enumerate(value):
                check(v, f"{where}[{i}]")
            return
        if not isinstance(value, dict):
            return
        if "@context" in value:
            ctxs = value["@context"] if isinstance(value["@context"], list) else [value["@context"]]
            for ctx in ctxs:
                if ctx == url:
                    continue
                if not isinstance(ctx, dict):
                    _fail(where, f"a remote context {ctx!r} other than the published one")
                for term, definition in ctx.items():
                    if term.startswith("@"):
                        _fail(where, f"`{term}` in an embedded context changes how protected terms read")
                    if term in terms and definition != terms[term]:
                        _fail(where, f"protected term redefinition: `{term}`")
        for k, v in value.items():
            if k != "@context":
                check(v, f"{where}.{k}")

    if not isinstance(document, dict) or "@context" not in document:
        _fail("jsonld", "a document names the published context")
    check(document, "jsonld")
    doc = dict(document, **{"@context": resolve(document["@context"])})
    doc = _resolve_nested(doc, resolve)
    return Graph().parse(data=json.dumps(doc), format="json-ld", base=schema["base"])


def _resolve_nested(value, resolve):
    if isinstance(value, list):
        return [_resolve_nested(v, resolve) for v in value]
    if isinstance(value, dict):
        return {k: (resolve(v) if k == "@context" else _resolve_nested(v, resolve)) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------------------------------------------
# The converter: rows ↔ RDF, without loss (T03)


def _literal(schema: dict, slot: dict, value) -> Literal:
    """A known value as a typed literal whose lexical form is the row JSON literal (§5)."""
    lexical = ("true" if value else "false") if isinstance(value, bool) else str(value)
    return Literal(lexical, datatype=URIRef(_type_iri(schema, slot["type"])), normalize=False)


def _object(schema: dict, slot: dict, value):
    if "ref" in slot:
        if "." in slot["ref"]:
            _fail(slot["ref"], "a reference into another pack has no IRI here: its base is not imported (Q20)")
        return URIRef(element_iri(schema, slot["ref"], value["$ref"]))
    return _literal(schema, slot, value)


def _annotate(g: Graph, triple, predicate, value):
    """An annotation on a statement: an `rdf:Statement` reifier (RDF 1.2 triple terms are not in rdflib 7.6)."""
    r = _bnode("a", *triple, predicate, value)
    g.add((r, RDF.type, RDF.Statement))
    g.add((r, RDF.subject, triple[0]))
    g.add((r, RDF.predicate, triple[1]))
    g.add((r, RDF.object, triple[2]))
    g.add((r, predicate, value))


def to_graph(schema: dict, rows: list) -> Graph:
    """The full RDF view of a dataset (§5). The rows are read first (`l0.read_rows`)."""
    l0.check_schema(schema)
    l0.read_rows(schema, rows)
    g = Graph()
    g.bind("rd", RD)
    for name, kind in sorted(schema["kinds"].items()):
        if kind["world"] == "closed":
            g.add((URIRef(kind_iri(schema, name)), RD.world, RD.closed))
        if "parent" in kind:
            g.add((URIRef(kind_iri(schema, name)), RDFS.subClassOf, URIRef(kind_iri(schema, kind["parent"]))))
    for row in rows:
        name = row["$kind"]
        kind = schema["kinds"][name]
        if "versioned" in kind:
            _fail(name, "a versioned kind has no RDF form yet (Q13)")
        s = URIRef(element_iri(schema, name, row["$id"]))
        typed = (s, RDF.type, URIRef(kind_iri(schema, name)))
        g.add(typed)
        stated = {"$id": [typed]}
        for slot_name, slot in kind["slots"].items():
            if "inverse" in slot:
                continue
            p = URIRef(slot_iri(schema, name, slot_name))
            value = row[slot_name]
            state = l0._state_of(value)
            if state is not None:
                b = _bnode("s", s, p)
                g.add((s, p, b))
                g.add((b, _STATE_TERMS[state[0]], Literal(state[1])))
                stated[slot_name] = [(s, p, b)]
            elif slot["card"] in ("*", "+"):
                if not value:
                    stated[slot_name] = [(s, p, RD.emptySet)]
                else:
                    stated[slot_name] = [(s, p, _object(schema, slot, m)) for m in value]
                for t in stated[slot_name]:
                    g.add(t)
            else:
                stated[slot_name] = [(s, p, _object(schema, slot, value))]
                g.add(stated[slot_name][0])
        for slot_name, proof in row.get("$why", {}).items():
            if isinstance(proof, dict):  # a many-valued slot: member payload → proof
                for t in stated[slot_name]:
                    member = _member_payload(schema, kind["slots"][slot_name], t[2])
                    if member in proof:
                        _annotate(g, t, RD.why, URIRef(proof[member]))
            else:
                _annotate(g, stated[slot_name][0], RD.why, URIRef(proof))
        for slot_name, sources in row.get("$src", {}).items():
            for source in sources:
                _annotate(g, stated[slot_name][0], RD.source, Literal(canonical_json(source), datatype=RDF.JSON))
    return bind_namespaces(g)


def _member_payload(schema: dict, slot: dict, term) -> str:
    """The payload of a member (§3.2) as `$why` keys it: text as is, else its canonical JSON."""
    value = _value(schema, slot, term)
    payload = l0._known(schema, slot, value, "member")
    return payload if isinstance(payload, str) else canonical_json(payload)


def _value(schema: dict, slot: dict, term):
    """A known value of row JSON from its RDF term."""
    if "ref" in slot:
        if not isinstance(term, URIRef):
            _fail(str(term), "a reference is an IRI")
        return {"$ref": _id_of(schema, slot["ref"], str(term))}
    if not isinstance(term, Literal) or str(term.datatype) != _type_iri(schema, slot["type"]):
        _fail(str(term), f"not a literal of type {_type_iri(schema, slot['type'])}")
    lexical = str(term)
    t = l0._local_type(schema, slot["type"])
    if t["of"] == "Bool":
        if lexical not in ("true", "false"):
            _fail(lexical, "a Bool is `true` or `false`")
        return lexical == "true"
    if t["of"] == "Integer" and l0._number_spelling(t):
        return int(l0._integer_text(lexical, "literal"))
    return lexical


def _id_of(schema: dict, kind: str, iri: str) -> str:
    prefix = f"{element_space(schema, kind)}/"
    if not iri.startswith(prefix) or not iri[len(prefix):]:
        _fail(iri, f"not the IRI of a {kind}")
    return unspell(iri[len(prefix):])


def _annotations(g: Graph) -> dict:
    """(subject, predicate, object) → [(annotation predicate, value), …] from the `rdf:Statement` reifiers."""
    out = {}
    for r in g.subjects(RDF.type, RDF.Statement):
        t = (g.value(r, RDF.subject), g.value(r, RDF.predicate), g.value(r, RDF.object))
        for p, o in g.predicate_objects(r):
            if p in (RD.why, RD.source):
                out.setdefault(t, []).append((p, o))
    return out


def from_graph(schema: dict, g: Graph) -> list:
    """The rows of a dataset from its full RDF view; inverse of `to_graph`. The rows are read (`l0.read_rows`)."""
    l0.check_schema(schema)
    notes = _annotations(g)
    rows = []
    for name, kind in sorted(schema["kinds"].items()):
        if "versioned" in kind:
            if any(g.subjects(RDF.type, URIRef(kind_iri(schema, name)))):
                _fail(name, "a versioned kind has no RDF form yet (Q13)")
            continue
        below = [URIRef(kind_iri(schema, k)) for k in schema["kinds"] if name in l0.chain(schema, k)[1:]]
        for s in sorted(g.subjects(RDF.type, URIRef(kind_iri(schema, name))), key=str):
            if any((s, RDF.type, b) in g for b in below):
                continue  # typed as a subkind too (an RDFS closure): the element is read once, at that kind
            row = {"$kind": name, "$id": _id_of(schema, name, str(s))}
            why, src = {}, {}
            triples = {"$id": [(s, RDF.type, URIRef(kind_iri(schema, name)))]}
            for slot_name, slot in kind["slots"].items():
                if "inverse" in slot:
                    continue
                p = URIRef(slot_iri(schema, name, slot_name))
                objects = sorted(g.objects(s, p), key=lambda o: (isinstance(o, BNode), str(o)))
                where = f"{name}/{row['$id']}.{slot_name}"
                triples[slot_name] = [(s, p, o) for o in objects]
                if len(objects) == 1 and isinstance(objects[0], BNode):
                    state = list(g.predicate_objects(objects[0]))
                    if len(state) != 1 or state[0][0] not in _STATE_TERMS.values():
                        _fail(where, "a state is a blank node with one of rd:unknown, rd:notApplicable, rd:invalid")
                    code = next(k for k, v in _STATE_TERMS.items() if v == state[0][0])
                    row[slot_name] = {_STATE_KEY[code]: str(state[0][1])}
                elif slot["card"] in ("*", "+"):
                    if objects == [RD.emptySet]:
                        row[slot_name] = []
                    elif not objects or RD.emptySet in objects or any(isinstance(o, BNode) for o in objects):
                        _fail(where, "a set is its members, or rd:emptySet alone, or one state")
                    else:
                        members = [_value(schema, slot, o) for o in objects]
                        row[slot_name] = sorted(members, key=lambda m: canonical_json(m).encode("utf-8"))
                else:
                    if len(objects) != 1:
                        _fail(where, f"a single-valued slot has one object, not {len(objects)}")
                    row[slot_name] = _value(schema, slot, objects[0])
            for slot_name, ts in triples.items():
                for t in ts:
                    for p, o in notes.get(t, []):
                        if p == RD.why:
                            if slot_name != "$id" and kind["slots"][slot_name]["card"] in ("*", "+") \
                                    and t[2] != RD.emptySet and not isinstance(t[2], BNode):
                                member = _member_payload(schema, kind["slots"][slot_name], t[2])
                                why.setdefault(slot_name, {})[member] = str(o)
                            else:
                                why[slot_name] = str(o)
                        else:
                            src.setdefault(slot_name, set()).add(str(o))
            if why:
                row["$why"] = why
            if src:
                row["$src"] = {k: [json.loads(t) for t in sorted(v)] for k, v in src.items()}
            rows.append(row)
    return l0.read_rows(schema, rows)


def _parse(text: str, form: str) -> Graph:
    """Parse without rdflib's literal normalisation: a lexical form is read as written and then held to its normal
    form by the reader, never rewritten (§1: no silent conversion)."""
    before = rdflib.NORMALIZE_LITERALS
    rdflib.NORMALIZE_LITERALS = False
    try:
        return Graph().parse(data=text, format=form)
    finally:
        rdflib.NORMALIZE_LITERALS = before


class _Turtle(TurtleSerializer):
    """rdflib's Turtle (7.6), without its quadratic search for a prefixed name. rdflib files the namespace of every
    IRI it writes in one trie and, for each subject and object, scans every namespace filed below that IRI's own:
    an element id spelled with `~` (§3.4) or a witness hash that starts with a digit gives a namespace of its own,
    so the scan grows with the graph (on a merged pack of 307,000 triples, over twenty minutes for one view).

    Only a bound namespace can stand in a prefixed name, and a namespace rdflib files for another IRI never
    starts this one beyond its own split: such a namespace ends just before a letter, so it would have split this
    IRI there too. So rdflib's choice is the longest bound namespace that starts the IRI and extends its split,
    else the split itself; that is computed here from the bound namespaces alone, and the text is rdflib's (the
    tests hold the bytes to `Graph.serialize`). A predicate keeps rdflib's own path, which may bind a prefix."""

    def __init__(self, store: Graph):
        super().__init__(store)
        self._bound: dict[str, str] = {}
        self._lengths: list[int] = []
        self._learn_bound()

    def _learn_bound(self) -> None:
        for prefix, ns in self.store.namespaces():
            self._learn(prefix, str(ns))

    def _learn(self, prefix: str, ns: str) -> None:
        if ns not in self._bound:
            self._bound[ns] = prefix
            self._lengths = sorted({*self._lengths, len(ns)})

    def _parts(self, uri: str):
        """(prefix, namespace, local) as `compute_qname(uri, generate=False)` gives them, or None."""
        if _is_valid_uri(uri):
            try:
                split = split_uri(uri)[0]
            except ValueError:
                split = None
            if split is not None:
                longest = next((uri[:n] for n in reversed(self._lengths)
                                if len(split) <= n <= len(uri) and uri[:n] in self._bound), split)
                if longest in self._bound:
                    return self._bound[longest], URIRef(longest), uri[len(longest):]
        if uri in self._bound:  # rdflib: is the IRI a namespace in itself?
            return self._bound[uri], URIRef(uri), ""
        return None

    def get_pname(self, uri, gen_prefix: bool = True):
        if not isinstance(uri, URIRef):
            return None
        if gen_prefix:
            name = super().get_pname(uri, gen_prefix)
            if name is not None:  # it may have bound a prefix of its own
                prefix = name.split(":", 1)[0]
                self._learn(prefix, str(self.namespaces[prefix]))
            else:  # it may have bound one and still given no name (a local name on `.`): later IRIs use it
                self._learn_bound()
            return name
        parts = self._parts(str(uri))
        if parts is None:
            return None
        prefix, namespace, local = parts
        local = local.replace(r"(", r"\(").replace(r")", r"\)")
        local = self.LOCALNAME_PECRENT_CHARACTER_REQUIRING_ESCAPE_REGEX.sub("\\%", local)
        if local.endswith("."):
            return None
        return f"{self.addNamespace(prefix, namespace)}:{local}"


def turtle(g: Graph) -> str:
    """`g.serialize(format="turtle")`, the same text, in a time that grows with the graph and not its square."""
    out = io.BytesIO()
    _Turtle(g).serialize(out, base=g.base, encoding="utf-8")
    return out.getvalue().decode("utf-8")


def to_turtle(schema: dict, rows: list) -> str:
    return turtle(to_graph(schema, rows))


def from_turtle(schema: dict, text: str) -> list:
    return from_graph(schema, _parse(text, "turtle"))


def to_jsonld(schema: dict, rows: list) -> str:
    """The converter's JSON-LD: the full view as expanded JSON-LD (T03)."""
    return to_graph(schema, rows).serialize(format="json-ld")


def from_jsonld(schema: dict, text: str) -> list:
    return from_graph(schema, _parse(text, "json-ld"))


# ---------------------------------------------------------------------------------------------------------------
# a witness as PROV-O


def row_iri(ref: dict) -> URIRef:
    """`rezono:r/<relation>/<key>`, each spelled as an id is (§3.4): a RowRef (contracts/proof.yaml) as an IRI."""
    return URIRef(f"{REZONO}r/{spell(ref['relation'])}/{spell(ref['key'])}")


def _row_ref(iri) -> dict:
    text = str(iri)
    if not text.startswith(REZONO + "r/") or text.count("/") != 2:
        _fail(text, "not a row IRI `rezono:r/<relation>/<key>`")
    relation, key = text[len(REZONO) + 2:].split("/")
    return {"relation": unspell(relation), "key": unspell(key)}


def witness_iri(witness: dict) -> URIRef:
    """`rezono:w/<canonical_sha256(witness)>`, as the `$why` of a row names it."""
    return URIRef(f"{REZONO}w/{canonical_sha256(witness)}")


def _row_entity_iri(ref: dict, schema: dict | None, *, require_schema: bool = False) -> URIRef:
    if schema is None:
        return row_iri(ref)
    mapped = _ref_to_kind_id(schema, ref)
    if mapped is not None:
        return URIRef(element_iri(schema, mapped[0], mapped[1]))
    if require_schema:
        _fail(str(ref), "witness conclusion does not map to a kind of this schema")
    return row_iri(ref)


def _row_ref_under(iri, schema: dict | None) -> dict:
    if schema is None:
        return _row_ref(iri)
    text = str(iri)
    if text.startswith(REZONO + "r/"):
        return _row_ref(text)
    space, sep, segment = text.rpartition("/")
    if not sep or not segment:
        _fail(text, "not a canonical row IRI of this schema")
    _, kind_to_rel = _schema_relation_maps(schema)
    space_to_kind = {element_space(schema, name): name for name in kind_to_rel}
    kind = space_to_kind.get(space)
    if kind is None:
        _fail(text, "not a canonical row IRI of this schema")
    row_id = unspell(segment)
    key = row_id if "tuple_key" in schema["kinds"][kind] else canonical_json([row_id])
    return {"relation": kind_to_rel[kind], "key": key}


def witness_to_prov(witness: dict, manifest: str, dataset: str, sources=None, *,
                    schema: dict | None = None) -> Graph:
    """One witness as PROV-O, in a graph named by its epoch, a `prov:Bundle`.

    `manifest` and `dataset` pin the epoch (`m-<epoch>` with its hash pin `d-…`, §6.4). `sources` maps a base
    row's `(relation, key)` to its Source objects: they become `prov:wasDerivedFrom`. When `schema` is given,
    the bundle, witness activity, conclusion entity and schema-known premise entities use their canonical IRIs.
    """
    if not isinstance(manifest, str) or not l0._MID.fullmatch(manifest) or not isinstance(dataset, str) or not l0._DID.fullmatch(dataset):
        _fail("epoch", "an epoch is `m-<epoch>` with its hash pin `d-<64 hex>` (§6.4)")
    if schema is not None:
        l0.check_schema(schema)
        bundle = URIRef(f"{schema['base']}{manifest}@{dataset}")
        a = URIRef(canonical_witness_iri(schema, witness))
        conclusion = _row_entity_iri(witness["conclusion"], schema, require_schema=True)
    else:
        bundle = URIRef(f"{REZONO}m/{manifest}@{dataset}")
        a = witness_iri(witness)
        conclusion = row_iri(witness["conclusion"])
    g = Graph(identifier=bundle)
    g.bind("prov", PROV)
    g.bind("rd", RD)
    g.add((bundle, RDF.type, PROV.Bundle))
    g.add((a, RDF.type, PROV.Activity))
    g.add((a, RD.rule, Literal(witness["rule_id"])))
    g.add((conclusion, RDF.type, PROV.Entity))
    g.add((conclusion, PROV.wasGeneratedBy, a))
    for i, premise in enumerate(witness.get("premises", [])):
        p = _row_entity_iri(premise["row"], schema)
        u = _bnode("u", a, i)
        g.add((p, RDF.type, PROV.Entity))
        g.add((a, PROV.used if premise["polarity"] == "positive" else RD.absent, p))
        g.add((a, PROV.qualifiedUsage, u))
        g.add((u, RDF.type, PROV.Usage))
        g.add((u, PROV.entity, p))
        g.add((u, RD.polarity, Literal(premise["polarity"])))
        g.add((u, RD.stratum, Literal(str(premise["stratum"]), datatype=XSD.integer)))
        g.add((u, RD.position, Literal(str(i), datatype=XSD.integer)))
        if premise["polarity"] == "positive":
            g.add((conclusion, PROV.wasDerivedFrom, p))
    for i, b in enumerate(witness.get("bindings", [])):
        n = _bnode("b", a, i)
        g.add((a, RD.binding, n))
        g.add((n, RD.variable, Literal(b["variable"])))
        g.add((n, RD.value, Literal(b["value"])))
        g.add((n, RD.position, Literal(str(i), datatype=XSD.integer)))
    for i, agg in enumerate(witness.get("aggregates", [])):
        g.add((a, RD.aggregate, Literal(_json({"i": i, "a": agg}), datatype=RDF.JSON)))
    for (relation, key), objs in sorted((sources or {}).items()):
        entity = _row_entity_iri({"relation": relation, "key": key}, schema)
        for source in objs:
            g.add((entity, PROV.wasDerivedFrom, Literal(canonical_json(source), datatype=RDF.JSON)))
    return bind_namespaces(g)


def _json(value) -> str:
    """JSON with sorted keys and integers kept as numbers (an aggregate's `count`), for an `rdf:JSON` literal."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def prov_to_witness(g: Graph, *, schema: dict | None = None) -> dict:
    """The witness of a graph made by `witness_to_prov`: the round trip loses nothing (O12c, M08)."""
    if schema is not None:
        l0.check_schema(schema)
    activities = list(g.subjects(RDF.type, PROV.Activity))
    if len(activities) != 1:
        _fail("prov", f"one prov:Activity per witness, not {len(activities)}")
    a = activities[0]
    conclusions = list(g.subjects(PROV.wasGeneratedBy, a))
    if len(conclusions) != 1:
        _fail("prov", "one conclusion `prov:wasGeneratedBy` the activity")
    witness = {"conclusion": _row_ref_under(conclusions[0], schema), "rule_id": str(g.value(a, RD.rule))}

    def ordered(nodes):
        return sorted(nodes, key=lambda n: int(g.value(n, RD.position)))

    bindings = [{"variable": str(g.value(n, RD.variable)), "value": str(g.value(n, RD.value))}
                for n in ordered(g.objects(a, RD.binding))]
    premises = [{"row": _row_ref_under(g.value(u, PROV.entity), schema), "polarity": str(g.value(u, RD.polarity)),
                 "stratum": int(g.value(u, RD.stratum))} for u in ordered(g.objects(a, PROV.qualifiedUsage))]
    aggregates = [json.loads(str(o)) for o in g.objects(a, RD.aggregate)]
    aggregates = [x["a"] for x in sorted(aggregates, key=lambda x: x["i"])]
    for member, value in (("bindings", bindings), ("premises", premises), ("aggregates", aggregates)):
        if value:
            witness[member] = value
    expected = URIRef(canonical_witness_iri(schema, witness)) if schema is not None else witness_iri(witness)
    if expected != a:
        _fail(str(a), "the activity's IRI is not the hash of the witness read back")
    return witness
