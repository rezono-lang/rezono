"""Validate packet rule records for the offline router fixture."""

from collections.abc import Iterable, Mapping

_IDENTITIES = ("source", "destination", "function")
_ADDRESSES = ("sourceFrom", "sourceTo", "destinationAddress")
_PORTS = ("fromPort", "toPort")
_FIELDS = {*_IDENTITIES, *_ADDRESSES, *_PORTS, "protocol"}


def validate(rules: Iterable[Mapping[str, object]]) -> None:
    """Require complete, ordered packet fields while retaining every witness."""
    for number, rule in enumerate(rules, 1):
        label = f"packet rule {number}"
        if not isinstance(rule, Mapping) or rule.keys() != _FIELDS:
            raise ValueError(f"{label} has missing or unknown fields")
        if any(not isinstance(rule[field], str) or not rule[field].strip() for field in _IDENTITIES):
            raise ValueError(f"{label} requires source, destination and function identities")
        if rule["protocol"] not in ("TCP", "UDP"):
            raise ValueError(f"{label} requires TCP or UDP")
        for field in _ADDRESSES:
            value = rule[field]
            if type(value) is not int or not 0 <= value < 2**32:
                raise ValueError(f"{label} requires an integer IPv4 address at {field}")
        for field in _PORTS:
            value = rule[field]
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError(f"{label} requires an integer port in 1..65535 at {field}")
        if rule["sourceFrom"] > rule["sourceTo"] or rule["fromPort"] > rule["toPort"]:
            raise ValueError(f"{label} has an inverted inclusive range")
