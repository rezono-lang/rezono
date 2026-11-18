"""Account for declared firewall witnesses using positive fixture cases."""

from collections.abc import Iterable, Mapping
from typing import NotRequired, TypedDict


class Endpoint(TypedDict):
    zone: str
    address: int


class Rule(TypedDict):
    source: NotRequired[str]
    destination: NotRequired[str]
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


class RuleCoverage(TypedDict):
    rule: Rule
    caseIds: list[str]


def _rule_order(rule: Rule) -> tuple[str, int, int, int, str, int, int, str, str]:
    return (
        rule["function"], rule["sourceFrom"], rule["sourceTo"], rule["destinationAddress"],
        rule["protocol"], rule["fromPort"], rule["toPort"], rule.get("source", ""),
        rule.get("destination", ""),
    )


def coverage(
    endpoints: Mapping[str, Endpoint], rules: Iterable[Rule], cases: Iterable[Case]
) -> list[RuleCoverage]:
    """Return each declared rule with its own positive cross-zone case IDs."""
    positive = []
    for case in cases:
        source, destination = endpoints[case["source"]], endpoints[case["destination"]]
        if case["router"] == case["service"] == "allow" and source["zone"] != destination["zone"]:
            positive.append((case, source["address"], destination["address"]))

    covered: list[RuleCoverage] = []
    for rule in sorted(rules, key=_rule_order):
        matching = {
            case["id"]
            for case, source, destination in positive
            if (
                rule["sourceFrom"] <= source <= rule["sourceTo"]
                and destination == rule["destinationAddress"]
                and case["protocol"] == rule["protocol"]
                and rule["fromPort"] <= case["port"] <= rule["toPort"]
            )
        }
        covered.append({"rule": rule.copy(), "caseIds": sorted(matching)})
    return covered
