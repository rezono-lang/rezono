"""Source-row provenance for the subject declarations of a Turtle view."""

import hashlib
import io
from collections.abc import Mapping

from rdflib import URIRef

from . import rdf


class _IndexedTurtle(rdf._Turtle):
    def __init__(self, graph):
        super().__init__(graph)
        self.line = 1
        self.subject_lines: dict[URIRef, int] = {}

    def write(self, text: str) -> None:
        super().write(text)
        self.line += text.count("\n")

    def s_default(self, subject):
        if isinstance(subject, URIRef):
            # The inherited serializer starts every declaration with a newline.
            self.subject_lines[subject] = self.line + 1
        return super().s_default(subject)


def indexed_view(
    schema: dict, rows: list, refs: Mapping[tuple[str, str], dict[str, str]]
) -> tuple[bytes, dict]:
    """Export the Turtle view and bind its subject lines to authoritative row references."""
    graph = rdf.to_graph(schema, rows)
    with io.BytesIO() as stream:
        serializer = _IndexedTurtle(graph)
        serializer.serialize(stream, base=graph.base, encoding="utf-8")
        body = stream.getvalue()

    entries: set[tuple[int, str, str]] = set()
    for row in rows:
        kind, element_id = row["$kind"], row["$id"]
        try:
            source = refs[kind, element_id]
        except KeyError as error:
            raise ValueError(f"missing source row for {kind}/{element_id}") from error
        subject = URIRef(rdf.element_iri(schema, kind, element_id))
        entries.add((serializer.subject_lines[subject], source["relation"], source["key"]))

    fields = [
        {"line": line, "origin": "knowledge", "witness": {"relation": relation, "key": key}}
        for line, relation, key in sorted(entries)
    ]
    return body, {"path": "view.ttl", "sha256": hashlib.sha256(body).hexdigest(), "fields": fields}
