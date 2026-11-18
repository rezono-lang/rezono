"""Bind the ODCS contract name to its publication schema."""

from hashlib import sha256

from rezono_canon import canonical_json

import odcs


def indexed_contract(schema: dict, pin: dict | None = None) -> tuple[bytes, dict]:
    """Return the regular ODCS YAML and the schema origin of its name."""
    body = odcs.to_yaml(schema, pin).encode("utf-8")
    schema_bytes = canonical_json(schema).encode("utf-8")
    return body, {
        "path": "contract.odcs.yaml",
        "sha256": sha256(body).hexdigest(),
        "fields": [{
            "pointer": "/name",
            "origin": "schema",
            "document": {
                "file": "schema.json",
                "sha256": sha256(schema_bytes).hexdigest(),
                "pointer": "/pack",
            },
        }],
    }
