"""Render the NoCloud meta-data that names a node after its machine."""

import re

_DNS_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def meta_data(machine_id):
    """Return the NoCloud meta-data for a machine ID that is a DNS-1123 label."""
    if not isinstance(machine_id, str) or not _DNS_LABEL.fullmatch(machine_id):
        raise ValueError("machine ID must be a DNS-1123 label")
    return f"instance-id: {machine_id}\nlocal-hostname: {machine_id}\n".encode()
