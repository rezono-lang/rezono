"""Prepare installer inputs from observed machine and disk records."""

from collections.abc import Iterable, Mapping
from ipaddress import ip_address

Machine = tuple[str, str, str, str]


def required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"machine observation requires nonempty {field}")
    return value


def machines(records: Iterable[Mapping[str, object]]) -> list[Machine]:
    """Return machine-ID ordered tuples without changing boot or data disk roles."""
    result: list[Machine] = []
    machine_ids: set[str] = set()
    disks: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("machine observation must be a record")
        identifier = required_text(record, "id")
        address = required_text(record, "address")
        boot = required_text(record, "boot_disk")
        data = required_text(record, "data_disk")
        ip_address(address)
        if identifier in machine_ids:
            raise ValueError(f"duplicate machine identity: {identifier}")
        if boot == data or boot in disks or data in disks:
            raise ValueError(f"machine {identifier} requires two distinct, unshared disks")

        machine_ids.add(identifier)
        disks.update((boot, data))
        result.append((identifier, address, boot, data))
    return sorted(result)
