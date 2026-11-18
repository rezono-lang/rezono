"""Line provenance for the property names in the SHACL schema export."""

from hashlib import sha256
from io import BytesIO

from rdflib import Graph, Namespace
from rdflib.namespace import SH
from rdflib.plugins.serializers.turtle import TurtleSerializer
from rdflib.term import Node

import shacl
from rezono_canon import canonical_json


class _IndexedShapesSerializer(TurtleSerializer):
    def __init__(self, graph: Graph) -> None:
        super().__init__(graph)
        self.line = 1
        self.subject: Node | None = None
        self.name_lines: dict[Node, int] = {}

    def write(self, text: str) -> None:
        super().write(text)
        self.line += text.count("\n")

    def predicateList(self, subject: Node, newline: bool = False) -> None:
        previous, self.subject = self.subject, subject
        try:
            super().predicateList(subject, newline)
        finally:
            self.subject = previous

    def verb(self, node: Node, newline: bool = False) -> None:
        if node == SH.name and self.subject is not None:
            self.name_lines[self.subject] = self.line
        super().verb(node, newline)


def _pointer(*parts: str) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def indexed_shapes(schema: dict) -> tuple[bytes, dict]:
    """Return the SHACL Turtle with each emitted property name's schema origin."""
    graph = shacl.shapes(schema)
    serializer = _IndexedShapesSerializer(graph)
    with BytesIO() as stream:
        serializer.serialize(stream, base=graph.base, encoding="utf-8")
        body = stream.getvalue()

    source_digest = sha256(canonical_json(schema).encode("utf-8")).hexdigest()
    namespace = Namespace(shacl.document_iri(schema) + "#")
    fields = []
    for kind, declaration in schema["kinds"].items():
        for name, slot in declaration["slots"].items():
            if "inverse" in slot:
                continue
            fields.append({
                "line": serializer.name_lines[namespace[f"{kind}.{name}"]],
                "origin": "schema",
                "document": {"file": "schema.json", "sha256": source_digest,
                             "pointer": _pointer("kinds", kind, "slots", name)},
            })

    return body, {"path": "shapes.ttl", "sha256": sha256(body).hexdigest(),
                  "fields": sorted(fields, key=lambda field: field["line"])}
