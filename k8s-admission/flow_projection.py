"""Project verified flow rows into parameters for one namespace."""

from collections.abc import Iterable
from typing import TypedDict


class FlowEntry(TypedDict):
    source: str
    destination: str
    port: int


def project_flows(
    namespace: str, rows: Iterable[tuple[str, str, str, int]]
) -> list[FlowEntry]:
    """Preserve unique flow tuples in source, destination and numeric port order."""
    flows = {(source, destination, port) for scope, source, destination, port in rows
             if scope == namespace}
    return [{"source": source, "destination": destination, "port": port}
            for source, destination, port in sorted(flows)]
