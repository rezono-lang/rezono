"""Account for declared firewall witnesses using positive fixture cases."""

from collections.abc import Iterable, Mapping
from typing import TypedDict


class Endpoint(TypedDict):
    zone: str
    address: int


class Rule(TypedDict):
    function: str
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
    router: str
    service: str


def coverage(
    endpoints: Mapping[str, Endpoint], rules: Iterable[Rule], cases: Iterable[Case]
) -> dict[str, list[str]]:
    """Return positive cross-zone case IDs per function, including empty coverage."""
    positive = []
    for case in cases:
        source, destination = endpoints[case["source"]], endpoints[case["destination"]]
        if case["router"] == case["service"] == "allow" and source["zone"] != destination["zone"]:
            positive.append((case, source["address"], destination["address"]))

    covered: dict[str, set[str]] = {}
    for rule in rules:
        matching = covered.setdefault(rule["function"], set())
        for case, source, destination in positive:
            if (
                rule["sourceFrom"] <= source <= rule["sourceTo"]
                and destination == rule["destinationAddress"]
                and case["protocol"] == rule["protocol"]
                and rule["fromPort"] <= case["port"] <= rule["toPort"]
            ):
                matching.add(case["id"])
    return {function: sorted(covered[function]) for function in sorted(covered)}
