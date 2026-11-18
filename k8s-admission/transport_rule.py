"""Wire identity shared by managed preflight and the release-bound CEL lookup."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowTable:
    field: str
    protocols: tuple[str, ...]
    implicit: bool


DEFAULT_PROTOCOL = "TCP"
EXPLICIT_PROTOCOLS = ("UDP", "SCTP")
FLOW_TABLES = (
    FlowTable("flows", (DEFAULT_PROTOCOL,), implicit=True),
    FlowTable("transportFlows", EXPLICIT_PROTOCOLS, implicit=False),
)


def published_identities(publication):
    identities = set()
    for table in FLOW_TABLES:
        rows = publication.get(table.field, None if table.implicit else [])
        if not isinstance(rows, list):
            raise ValueError(f"expected published {table.field} list")
        fields = {"source", "destination", "port"}
        if not table.implicit:
            fields.add("protocol")
        for row in rows:
            if not isinstance(row, dict) or row.keys() != fields:
                raise ValueError("invalid published flow fields")
            source, destination, port = row["source"], row["destination"], row["port"]
            protocol = DEFAULT_PROTOCOL if table.implicit else row["protocol"]
            if (not all(isinstance(s, str) and s for s in (source, destination))
                    or protocol not in table.protocols or type(port) is not int or not 1 <= port <= 65535):
                raise ValueError("invalid published flow identity")
            identity = (source, destination, protocol, port)
            if identity in identities:
                raise ValueError("duplicate published flow identity")
            identities.add(identity)
    return identities


def cel_range_coverage(source: str, destination: str) -> str:
    end = "(has(p.endPort) ? p.endPort : int(p.port))"
    match = (f"f.source == {source} && f.destination == {destination} && "
             f"f.port >= int(p.port) && f.port <= {end}")
    width = f"({end} - int(p.port) + 1)"
    alternatives = []
    for table in FLOW_TABLES:
        rows = f"params.spec.{table.field}"
        if table.implicit:
            selected = f"(!has(p.protocol) || p.protocol == '{DEFAULT_PROTOCOL}')"
            witness = match
        else:
            selected = f"has(p.protocol) && p.protocol in {list(table.protocols)!r} && has({rows})"
            witness = f"f.protocol == p.protocol && {match}"
        # The CRD's map keys make each port in the selected directional tuple unique.
        alternatives.append(f"({selected} && size({rows}.filter(f, {witness})) == {width})")
    return "(" + " || ".join(alternatives) + ")"
