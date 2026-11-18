"""Classify declared synthetic cases against modeled router allowances."""

from collections.abc import Iterable, Mapping
from typing import Literal, TypedDict


class Endpoint(TypedDict):
    zone: str
    address: int


class Allowance(TypedDict):
    sourceFrom: int
    sourceTo: int
    destinationAddress: int
    protocol: str
    fromPort: int
    toPort: int


class Case(TypedDict):
    id: str
    source: str
    destination: str
    protocol: str
    port: int


Verdict = Literal["allow", "deny", "inapplicable"]


def router_verdicts(
    endpoints: Mapping[str, Endpoint], rules: Iterable[Allowance], cases: Iterable[Case]
) -> dict[str, Verdict]:
    """Match the union of all rules for each named case that crosses zones."""
    allowances = tuple(rules)
    verdicts: dict[str, Verdict] = {}
    for case in sorted(cases, key=lambda case: case["id"]):
        case_id = case["id"]
        if not case_id or case_id in verdicts:
            raise ValueError(f"invalid or duplicate fixture case ID: {case_id!r}")
        source, destination = endpoints[case["source"]], endpoints[case["destination"]]
        if source["zone"] == destination["zone"]:
            verdicts[case_id] = "inapplicable"
            continue
        matched = any(
            rule["sourceFrom"] <= source["address"] <= rule["sourceTo"]
            and rule["destinationAddress"] == destination["address"]
            and rule["protocol"] == case["protocol"]
            and rule["fromPort"] <= case["port"] <= rule["toPort"]
            for rule in allowances
        )
        verdicts[case_id] = "allow" if matched else "deny"
    return verdicts
