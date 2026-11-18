"""Index the visible witness activities in a PROV-O export."""

from collections.abc import Iterable
from hashlib import sha256

from rdflib import Graph, URIRef
from rdflib.namespace import PROV, RDF

from . import rdf


def indexed_prov(manifest: str, dataset: str, witnesses: Iterable[dict]) -> tuple[bytes, dict]:
    """Return Turtle and the line bindings for the role's supplied witnesses."""
    graph = Graph()
    graph.bind("prov", PROV)
    graph.bind("rd", rdf.RD)
    bundle = URIRef(f"{rdf.REZONO}m/{manifest}@{dataset}")
    graph.add((bundle, RDF.type, PROV.Bundle))

    conclusions = {}
    for witness in sorted(witnesses, key=rdf.witness_iri):
        graph += rdf.witness_to_prov(witness, manifest, dataset)
        activity = rdf.witness_iri(witness).n3()
        conclusions[activity] = witness["conclusion"]

    turtle = rdf.turtle(rdf.bind_namespaces(graph))
    fields = []
    for line_number, line in enumerate(turtle.splitlines(), 1):
        subject, separator, _ = line.partition(" a prov:Activity")
        if separator and subject in conclusions:
            fields.append({"line": line_number, "origin": "knowledge", "witness": conclusions[subject]})

    body = turtle.encode("utf-8")
    return body, {"path": "prov.ttl", "sha256": sha256(body).hexdigest(), "fields": fields}
