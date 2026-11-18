"""Index DCAT access URLs against the listing of their own role and epoch."""

import re
from collections import Counter
from hashlib import sha256

import dcat
from rezono_publication import l0


def indexed_catalogue(
    schema: dict, pin: dict[str, str], files: dict[str, str], role: str, listing_bytes: bytes
) -> tuple[bytes, dict]:
    """Return the catalogue bytes and bind each access URL to its listed object name."""
    turtle = dcat.to_turtle(schema, pin, files)
    listing = l0.loads(listing_bytes.decode("utf-8"))
    expected = {"format": "rezono.publication-form/1", "pack": schema["pack"], "schema": l0.schema_id(schema),
                "role": role, **pin}
    if (not isinstance(role, str) or not role or not isinstance(listing, dict)
            or any(listing.get(key) != value for key, value in expected.items())):
        raise ValueError("index.json does not describe this role, schema and epoch")

    objects = listing.get("objects")
    if not isinstance(objects, list):
        raise ValueError("index.json has no object list")
    positions: dict[str, int] = {}
    for position, item in enumerate(objects):
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or name in positions:
            raise ValueError("index.json must name each object once")
        positions[name] = position

    addresses = Counter(files.values())
    for address in addresses:
        if not dcat._RELATIVE.fullmatch(address) or address not in positions:
            raise ValueError(f"no listed object for DCAT access URL {address!r}")

    digest = sha256(listing_bytes).hexdigest()
    fields = []
    # The catalogue's Turtle serializer writes each accessURL predicate on its own line.
    seen: Counter[str] = Counter()
    for number, line in enumerate(turtle.splitlines(), 1):
        match = re.fullmatch(r"dcat:accessURL\s+<([^>]+)>\s*[;.]", line.strip())
        if match is None:
            continue
        address = match[1]
        if address not in addresses:
            raise ValueError("catalogue contains an unexpected access URL")
        seen[address] += 1
        fields.append({"line": number, "origin": "role_listing", "document": {
            "file": "index.json", "sha256": digest, "pointer": f"/objects/{positions[address]}/name",
        }})
    if seen != addresses:
        raise ValueError("catalogue access URLs do not match the indexed forms")

    body = turtle.encode("utf-8")
    return body, {"path": "dcat.ttl", "sha256": sha256(body).hexdigest(), "fields": fields}
