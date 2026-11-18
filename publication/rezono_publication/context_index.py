"""Index the scoped slot types in a JSON-LD context against its schema."""

import json

from rezono_canon import canonical_sha256, sha256_hex

from . import rdf


def _pointer(*tokens: str) -> str:
    return "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in tokens)


def indexed_context(schema: dict) -> tuple[bytes, dict]:
    """Export the context and identify the schema member behind each scoped type."""
    context = rdf.context(schema)
    body = json.dumps(context, sort_keys=True, ensure_ascii=False, indent=1).encode("utf-8")
    schema_digest = canonical_sha256(schema)

    fields = []
    for kind, declaration in schema["kinds"].items():
        for slot, definition in declaration["slots"].items():
            member = "ref" if "ref" in definition else "type"
            fields.append({
                "pointer": _pointer("@context", kind, "@context", slot, "@type"),
                "origin": "schema",
                "document": {
                    "file": "schema.json",
                    "sha256": schema_digest,
                    "pointer": _pointer("kinds", kind, "slots", slot, member),
                },
            })
    fields.sort(key=lambda field: field["pointer"])
    return body, {"path": "context.jsonld", "sha256": sha256_hex(body), "fields": fields}
