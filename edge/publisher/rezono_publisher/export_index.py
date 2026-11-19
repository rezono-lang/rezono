"""The output index of a role's standards exports (decisions/export-output-index.md).

`exports.index.json` is an `OutputIndex` (contracts/output-index.yaml) of one render step, `standards_exports`: the
exports `forms.exports` made from one role's verified form. It lists every export file by path with the SHA-256 of
its published bytes, and in each file the fields the export took from the form, by their 1-based line or their
JSON pointer:

- a value of a published row (origin `knowledge`), whose witness is the `RowRef` of that row: relation and
  canonical JSON key, as the role's own files name it. A derived row is its own conclusion; a fact row is cited
  the same way. In the RDF view an element's subject line cites its identity rows, a value line the row of that
  value, and the lines of a statement about a value (`rdf:subject`, `rdf:object`, `rd:why`, `rd:source`) the row
  of the value it is about. In PROV-O every line that holds a term of a witness cites that witness's conclusion.
- a value taken from the role's schema (origin `schema`), which points into `schema.json` with its hash: the
  scoped types of the JSON-LD context, the property names of the SHACL shapes and the name of the ODCS contract.

Syntax the exporter writes itself (prefixes, punctuation, vocabulary terms) is not a field. A field is never
attributed to a row the role's files do not hold: a value with no such row is not cited.

The Turtle lines are those the serializer writes: `Lines` is the serializer of `rdf.turtle` that also notes, per
term it writes, its line, subject, predicate and position, so the same bytes are written and indexed in one pass.
"""

from __future__ import annotations

import hashlib
import io
import json

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, SH
from rdflib.plugins.serializers.turtle import OBJECT, SUBJECT, VERB, TurtleSerializer
from rezono_canon import canonical_bytes, canonical_json

NAME = "exports.index.json"
FORMAT = "rezono.output-index/1"
STEP = "standards_exports"
SCHEMA = "schema.json"


class Blocked(Exception):
    """The index does not say what the exports say: nothing is written."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pointer(*tokens: str) -> str:
    return "".join("/" + t.replace("~", "~0").replace("/", "~1") for t in tokens)


class _Noting:
    """A Turtle serializer that notes each term it writes: (line, subject, predicate, term, position). The text is
    the base serializer's own; only the line count and the notes are added."""

    def __init__(self, store: Graph):
        super().__init__(store)
        self.line = 1
        self.notes: list[tuple] = []
        self._subject = None
        self._predicate = None

    def write(self, text: str) -> None:
        super().write(text)
        self.line += text.count("\n")

    def predicateList(self, subject, newline: bool = False) -> None:
        saved = self._subject, self._predicate
        self._subject = subject
        try:
            super().predicateList(subject, newline)
        finally:
            self._subject, self._predicate = saved

    def path(self, node, position, newline: bool = False) -> None:
        if position == VERB:
            self._predicate = node
        else:
            self.notes.append((self.line, self._subject, self._predicate, node, position))
        super().path(node, position, newline)


def _serialize(cls, g: Graph) -> tuple[str, list[tuple]]:
    out = io.BytesIO()
    s = cls(g)
    s.serialize(out, base=g.base, encoding="utf-8")
    return out.getvalue().decode("utf-8"), s.notes


def lines(g: Graph) -> tuple[str, list[tuple]]:
    """`rdf.turtle(g)` and the notes of the terms it wrote."""
    from rezono_publication import rdf

    class Lines(_Noting, rdf._Turtle):
        pass

    return _serialize(Lines, g)


def _plain_lines(g: Graph) -> tuple[str, list[tuple]]:
    """`g.serialize(format="turtle")` and its notes."""

    class Lines(_Noting, TurtleSerializer):
        pass

    return _serialize(Lines, g)


def _ref(relation: str, key) -> tuple[str, str]:
    return relation, canonical_json(list(key))


def _knowledge(line: int, refs) -> list[dict]:
    return [{"line": line, "origin": "knowledge", "witness": {"relation": r, "key": k}} for r, k in sorted(refs)]


def view_rows(schema: dict, plan: dict, given: dict, form_rows: list[dict]) -> dict[tuple, set]:
    """Per triple of the RDF view that states a row of the role, that row: an element's type its identity rows, a
    value its slot row, a derived element's type and columns its derived row. `given` holds the role's own rows
    per relation, as its files give them; `form_rows` are the rows of its form (for each element's kind)."""
    from rezono_publication import l0, rdf
    from rezono_publication import publication as rd

    kind_of = {(l0.root(schema, r["$kind"]), r["$id"]): r["$kind"] for r in form_rows}
    out: dict[tuple, set] = {}

    def element(name: str, i: str) -> tuple[str, URIRef]:
        kind = kind_of.get((l0.root(schema, name), i))
        if kind is None:
            raise Blocked(f"{name} {i} is in the role's files, not in its form")
        return kind, URIRef(rdf.element_iri(schema, kind, i))

    for table, name in plan["kinds"].items():
        for key in given.get(table, []):
            kind, s = element(name, key[0])
            out.setdefault((s, RDF.type, URIRef(rdf.kind_iri(schema, kind))), set()).add(_ref(table, key))
    for table, (name, slot, a) in plan["slots"].items():
        for key in given.get(table, []):
            i, v = key
            kind, s = element(name, i)
            spec = schema["kinds"][kind]["slots"][slot]
            if "inverse" in spec:
                continue
            term = rdf._object(schema, spec, rd._value(schema, name, slot, a, v))
            out.setdefault((s, URIRef(rdf.slot_iri(schema, kind, slot)), term), set()).add(_ref(table, key))
    for relation, (name, columns) in plan["derived"].items():
        slots = schema["kinds"][name]["slots"]
        for key in given.get(relation, []):
            ref = _ref(relation, key)
            s = URIRef(rdf.element_iri(schema, name, ref[1]))
            out.setdefault((s, RDF.type, URIRef(rdf.kind_iri(schema, name))), set()).add(ref)
            for column, v in zip(columns, key):
                term = rdf._object(schema, slots[column], {"$ref": v} if "ref" in slots[column] else v)
                out.setdefault((s, URIRef(rdf.slot_iri(schema, name, column)), term), set()).add(ref)
    return out


def view_fields(schema: dict, g: Graph, notes: list[tuple], stated: dict[tuple, set]) -> list[dict]:
    """The knowledge fields of `view.ttl`, from the notes of its serializer and `view_rows`."""
    from rezono_publication import rdf

    kinds = {URIRef(rdf.kind_iri(schema, k)) for k in schema["kinds"]}
    about = (RDF.subject, RDF.object, rdf.RD.why, rdf.RD.source)
    identity: dict = {}
    for (s, p, _), refs in stated.items():
        if p == RDF.type:
            identity.setdefault(s, set()).update(refs)
    fields = []
    for line, subject, predicate, node, position in notes:
        if position == SUBJECT:
            refs = identity.get(node)
        elif isinstance(node, BNode) or node in kinds or (isinstance(node, URIRef) and str(node).startswith(str(rdf.RD))):
            continue  # a state, a set, a kind: no value of a row
        elif isinstance(subject, BNode) and predicate in about and (subject, RDF.type, RDF.Statement) in g:
            refs = stated.get((g.value(subject, RDF.subject), g.value(subject, RDF.predicate),
                               g.value(subject, RDF.object)))
        else:
            refs = stated.get((subject, predicate, node))
        if refs:
            fields += _knowledge(line, refs)
    return fields


def prov_fields(notes: list[tuple], owners: dict[tuple, set], bundle: URIRef) -> list[dict]:
    """The knowledge fields of `prov.ttl`: each line that writes a term of a witness (an activity, a row, a
    binding's value) cites the witness's conclusion. `owners` maps each triple to the conclusions whose witness
    states it."""
    by_subject: dict = {}
    for (s, _, _), refs in owners.items():
        by_subject.setdefault(s, set()).update(refs)
    fields = []
    for line, subject, predicate, node, position in notes:
        if position == SUBJECT:
            refs = by_subject.get(node) if node != bundle else None
        elif isinstance(node, Literal) or (isinstance(node, URIRef) and str(node).startswith("rezono:")):
            refs = owners.get((subject, predicate, node))
        else:
            continue  # a vocabulary term or a nested node: exporter syntax
        if refs:
            fields += _knowledge(line, refs)
    return fields


def _schema_field(place: dict, digest: str, pointer: str) -> dict:
    return {**place, "origin": "schema", "document": {"file": SCHEMA, "sha256": digest, "pointer": pointer}}


def context_fields(schema: dict, body: bytes, digest: str) -> list[dict]:
    """The scoped types of the JSON-LD context, each from its slot in schema.json (`context_index`)."""
    from rezono_publication.context_index import indexed_context

    made, record = indexed_context(schema)
    if made != body:
        raise Blocked("context.jsonld is not the context of the role's schema")
    return [_schema_field({"pointer": f["pointer"]}, digest, f["document"]["pointer"]) for f in record["fields"]]


def shapes_fields(shacl, schema: dict, body: bytes, digest: str) -> list[dict]:
    """The property names of the SHACL shapes, each from its slot declaration in schema.json."""
    text, notes = _plain_lines(shacl.shapes(schema))
    if text.encode("utf-8") != body:
        raise Blocked("shapes.ttl is not the shapes of the role's schema")
    ns = Namespace(shacl.document_iri(schema) + "#")
    slots = {ns[f"{k}.{n}"]: (k, n) for k, d in schema["kinds"].items() for n, s in d["slots"].items()
             if "inverse" not in s}
    return [_schema_field({"line": line}, digest, _pointer("kinds", slots[subject][0], "slots", slots[subject][1]))
            for line, subject, predicate, _, position in notes
            if position == OBJECT and predicate == SH.name and subject in slots]


def contract_fields(schema: dict, body: bytes, digest: str) -> list[dict]:
    """The contract's name, which copies the schema's pack."""
    import yaml

    if (yaml.safe_load(body) or {}).get("name") != schema["pack"]:
        raise Blocked("contract.odcs.yaml is not named after the role's schema")
    return [_schema_field({"pointer": "/name"}, digest, "/pack")]


def _order(field: dict) -> tuple:
    return field.get("line", 0), field.get("pointer", ""), canonical_json(field)


def index(pack: str, manifest: str, dataset: str, connectors: str, schema_bytes: bytes, rows_bytes: bytes,
          made: dict[str, bytes], fields: dict[str, list[dict]]) -> bytes:
    """The bytes of `exports.index.json`: identity, one file per export by path, its fields by line and pointer.
    Read back and held to the exports before it is returned; raises Blocked with what differs."""
    data = {
        "format": FORMAT, "pack": pack, "manifest": manifest,
        "render": {"step": STEP, "input_sha256": _sha(canonical_bytes({
            "connectors": connectors, "dataset": dataset, "manifest": manifest,
            "rows": _sha(rows_bytes), "schema": _sha(schema_bytes)}))},
        "files": [{"path": n, "sha256": _sha(made[n]),
                   "fields": sorted({canonical_json(f): f for f in fields.get(n, [])}.values(), key=_order)}
                  for n in sorted(made)],
    }
    out = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    check(json.loads(out), made, schema_bytes)
    return out


def check(data: dict, made: dict[str, bytes], schema_bytes: bytes) -> None:
    """An index read back from its bytes, held to the exports it indexes: each file once with its hash, each line
    in its file, each schema origin at the role's schema.json. Raises Blocked with what differs."""
    if [f["path"] for f in data["files"]] != sorted(made):
        raise Blocked("the index does not list exactly the exports")
    digest = _sha(schema_bytes)
    for f in data["files"]:
        if f["sha256"] != _sha(made[f["path"]]):
            raise Blocked(f"{f['path']}: the index names other bytes")
        count = len(made[f["path"]].decode("utf-8").splitlines())
        for field in f["fields"]:
            if "line" in field and not 1 <= field["line"] <= count:
                raise Blocked(f"{f['path']}: line {field['line']} is not in the file")
            if field["origin"] == "schema" and (field["document"]["file"], field["document"]["sha256"]) != (SCHEMA, digest):
                raise Blocked(f"{f['path']}: a schema field does not point into the role's schema.json")
