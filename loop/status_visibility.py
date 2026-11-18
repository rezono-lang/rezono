"""Tenant-scoped delivery status records."""

from collections.abc import Iterable, Iterator, Mapping


def visible(
    tenant: str, records: Iterable[Mapping[str, object]]
) -> Iterator[Mapping[str, object]]:
    """Yield only records owned by the tenant authenticated by the caller."""
    if not isinstance(tenant, str) or not tenant:
        return
    for record in records:
        if record.get("tenant") == tenant:
            yield record
