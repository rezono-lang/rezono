"""Render the offline fixture's packet rules for a default-deny router."""

from collections.abc import Iterable
from ipaddress import IPv4Address
import json
from typing import TypedDict


class PacketRule(TypedDict):
    source: str
    destination: str
    function: str
    sourceFrom: int
    sourceTo: int
    destinationAddress: int
    protocol: str
    fromPort: int
    toPort: int


def render(rules: Iterable[PacketRule]) -> bytes:
    """Render normalized rules, retaining the logical witness on each distinct line."""
    lines = set()
    for rule in rules:
        start = IPv4Address(rule["sourceFrom"])
        end = IPv4Address(rule["sourceTo"])
        source = str(start) if start == end else f"{start}-{end}"
        destination = IPv4Address(rule["destinationAddress"])
        low, high = rule["fromPort"], rule["toPort"]
        port = str(low) if low == high else f"{low}-{high}"
        witness = json.dumps([rule["source"], rule["destination"], rule["function"]], separators=(",", ":"))
        lines.add(
            f"        ip saddr {source} ip daddr {destination} "
            f"{rule['protocol'].lower()} dport {port} accept comment {json.dumps(witness)}"
        )

    return "\n".join([
        "table ip rezono_fixture {",
        "    chain forward {",
        "        type filter hook forward priority filter; policy drop;",
        *sorted(lines),
        "    }",
        "}",
        "",
    ]).encode("utf-8")
