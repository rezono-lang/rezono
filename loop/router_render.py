"""Render the offline fixture's packet rules for a default-deny router."""

from collections.abc import Iterable
import hashlib
from ipaddress import IPv4Address
import json
from typing import TypedDict

_NFT_COMMENT_MAX_BYTES = 128
_WITNESS_DIGEST_CHARS = 16


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


def _nft_comment(source: str, destination: str, function: str) -> str:
    """Format a deterministic, valid nftables quoted comment within 128 UTF-8 bytes."""
    canonical = json.dumps([source, destination, function], separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:_WITNESS_DIGEST_CHARS]
    suffix = f"|{digest}"
    label = f"{source}->{destination}:{function}"
    sanitized = "".join(
        "_" if ch in ('"', "\\", "\r", "\n") or ord(ch) < 32 or ord(ch) == 127 else ch
        for ch in label
    )
    max_prefix_bytes = _NFT_COMMENT_MAX_BYTES - len(suffix.encode("utf-8"))
    prefix_bytes = sanitized.encode("utf-8")
    if len(prefix_bytes) > max_prefix_bytes:
        sanitized = prefix_bytes[:max_prefix_bytes].decode("utf-8", errors="ignore")
    return f'"{sanitized}{suffix}"'


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
        comment = _nft_comment(rule["source"], rule["destination"], rule["function"])
        lines.add(
            f"        ip saddr {source} ip daddr {destination} "
            f"{rule['protocol'].lower()} dport {port} accept comment {comment}"
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
