"""Index the visible witness activities in a PROV-O export."""

from collections.abc import Iterable
from hashlib import sha256

from rdflib import Graph, URIRef
from rdflib.namespace import PROV, RDF

from . import l0, rdf


def indexed_prov(manifest: str, dataset: str, witnesses: Iterable[dict], *,
                 schema: dict | None = None) -> tuple[bytes, dict]:
    """Return Turtle and the line bindings for the role's supplied witnesses."""
    if schema is not None:
        l0.check_schema(schema)
    graph = Graph()
    graph.bind("prov", PROV)
    graph.bind("rd", rdf.RD)
    bundle = (URIRef(f"{schema['base']}{manifest}@{dataset}")
              if schema is not None else URIRef(f"{rdf.REZONO}m/{manifest}@{dataset}"))
    graph.add((bundle, RDF.type, PROV.Bundle))

    def activity_ref(witness: dict) -> URIRef:
        return URIRef(rdf.canonical_witness_iri(schema, witness)) if schema is not None else rdf.witness_iri(witness)

    conclusions = {}
    for witness in sorted(witnesses, key=activity_ref):
        graph += rdf.witness_to_prov(witness, manifest, dataset, schema=schema)
        activity = activity_ref(witness).n3()
        conclusions[activity] = witness["conclusion"]

    turtle = rdf.turtle(rdf.bind_namespaces(graph))
    fields = []
    for line_number, line in enumerate(turtle.splitlines(), 1):
        subject, separator, _ = line.partition(" a prov:Activity")
        if separator and subject in conclusions:
            fields.append({"line": line_number, "origin": "knowledge", "witness": conclusions[subject]})

    body = turtle.encode("utf-8")
    return body, {"path": "prov.ttl", "sha256": sha256(body).hexdigest(), "fields": fields}
