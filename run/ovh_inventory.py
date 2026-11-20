"""Read the unfiltered OVHcloud server list and find delivered services still listed, per decisions/run-price-enforcement.md, Cleanup."""

from collections.abc import Iterable, Mapping
from contextlib import closing
from functools import cache
import json
from pathlib import Path

from rezono_compiler import batch, facts, pack, rules, scenarios

_PACK_DIR = Path(__file__).resolve().parent / "packs" / "cleanup"


@cache
def _cleanup() -> tuple[pack.Pack, rules.Program]:
    model = pack.read(_PACK_DIR)
    return model, rules.load(model.rules)


def _reject_constant(token: str) -> object:
    raise ValueError(f"invalid JSON constant: {token}")


def _parse_listing(listing: bytes) -> set[str]:
    if not isinstance(listing, bytes):
        raise ValueError("listing must be bytes")
    try:
        document = json.loads(listing.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("listing is not valid UTF-8 JSON") from exc
    if not isinstance(document, list):
        raise ValueError("listing must be a JSON array")
    names: set[str] = set()
    for item in document:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("each listed service name must be a nonempty string")
        if item in names:
            raise ValueError(f"duplicate listed service name: {item!r}")
        names.add(item)
    return names


def _delivered_names(delivered: Iterable[str]) -> set[str]:
    if isinstance(delivered, (str, bytes, Mapping)) or not isinstance(delivered, Iterable):
        raise ValueError("delivered must be an iterable of service names")
    names: set[str] = set()
    for item in delivered:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("each delivered service name must be a nonempty string")
        names.add(item)
    return names


def request() -> tuple[str, str]:
    """Return the unfiltered account-wide server listing request."""
    return ("GET", "/dedicated/server")


def remaining(listing: bytes, delivered: Iterable[str]) -> list[str]:
    """Return sorted delivered service names that still appear in the unfiltered server listing."""
    listed = _parse_listing(listing)
    expected = _delivered_names(delivered)
    model, program = _cleanup()
    listing_id = "unfiltered"
    runtime_rows = facts.rows_of(model, {
        "listing": [{"id": listing_id, "coverage": "complete", "unfiltered": True}],
        "listed_service": [
            {"id": f"listed/{index}", "listing": listing_id, "service": name}
            for index, name in enumerate(sorted(listed))
        ],
        "delivered_service": [
            {"id": f"delivered/{index}", "service": name}
            for index, name in enumerate(sorted(expected))
        ],
    })
    inputs = scenarios.rule_rows(model, program, runtime_rows)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        rows = batch.read(connection, program, ["still_listed"])["still_listed"]
    return sorted(service for row_listing, service in rows if row_listing == listing_id)
