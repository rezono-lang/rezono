"""A service's port follows from its maker's statement unless a port decision overrides it
(decisions/platform-facts-not-conclusions.md, section 3).

The expected rows are the independent reference rows of oracle-rows.json, which the oracle computes from the offer
ports until a planner retires them, and the makers' pinned statements in facts/*_transport_source.yaml, read here
from the files themselves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parent
REPO = PLATFORM.parents[1]
DECISION = "port_decision"


def _rows():
    from rezono_compiler import scenarios
    from rules_support import states

    model, prog, _ = states(PLATFORM)
    label, raw = next(iter(scenarios.states(model, PLATFORM)))
    return model, prog, label, {table: list(values) for table, values in raw.items()}


def _derive(model, prog, label, rows):
    from rules_support import State

    return State(model, prog, label, rows).derived


def _statements() -> list[dict]:
    out = []
    for path in sorted((PLATFORM / "facts").glob("*_transport_source.yaml")):
        out += yaml.safe_load(path.read_text(encoding="utf-8"))["vendor_default_transport_source"]
    return out


def _decision_file(source: dict) -> bool:
    """A git source that names a decision file of this repository."""
    path = str(source.get("position", "")).partition("#")[0]
    return source.get("kind") == "git" and path.startswith("decisions/") and (REPO / path).is_file()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/platform-facts-not-conclusions.md, section 3. Derive provides from the PortDecision for the "
    "product and function where one exists, else from each vendor_default_transport_source statement whose series "
    "is the version or series of the release the service runs, else from the product's one stated series, and add "
    "port_unknown; choice_evidence.dl and unique_evidence.dl read provides instead of offer__port. Keep Offer.port: "
    "a planner retires it. Waits for the planner's sources step of section 3 (the eight port decisions with their "
    "origin, the PostgreSQL 16 statement and the restated incremental proof tests)."))
def test_service_port_follows_the_vendor_statement_unless_decided():
    from rezono_compiler import sources

    reference = {tuple(map(str, row)) for row in
                 json.loads((PLATFORM / "oracle-rows.json").read_text(encoding="utf-8"))["provides"]}
    model, prog, label, rows = _rows()
    assert f"{DECISION}__port" in prog.relations, "Missing kind PortDecision with product, function and port"
    derived = _derive(model, prog, label, rows)
    assert derived["provides"] == reference
    assert not derived.get("port_unknown"), derived.get("port_unknown")

    # A port decision departs from its maker's statement or stands where there is none; it never repeats one.
    statements = _statements()
    product = dict(rows[f"{DECISION}__product"])
    port = dict(rows[f"{DECISION}__port"])
    for decision, of in sorted(product.items()):
        stated = {int(s["port"]) for s in statements if s["product"] == of}
        assert int(port[decision]) not in stated, f"{decision} repeats the default port of {of}"

    # Each port decision has a decision file as its origin.
    cited = set()
    for path in sorted((PLATFORM / "facts").glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        if DECISION not in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}):
            continue
        for entry in sources.file_entries(model, path):
            if entry["row"]["relation"].split("__")[0] == DECISION and any(map(_decision_file, entry["sources"])):
                cited.add(json.loads(entry["row"]["key"])[0])
    assert set(product) <= cited, f"port decisions without a decision file as origin: {sorted(set(product) - cited)}"

    # The offer port decides nothing, while it is still written.
    if "offer__port" in rows:
        changed = dict(rows, offer__port=[(offer, 1) for offer, _ in rows["offer__port"]])
        assert _derive(model, prog, label, changed)["provides"] == reference, "provides still reads Offer.port"

    # The maker's statement for the release a service runs decides its port.
    keycloak = {s for s, of in rows["vendor_default_transport_source__product"] if of == "keycloak"}
    assert keycloak, "Missing the Keycloak transport statement"
    changed = dict(rows, vendor_default_transport_source__port=[
        (s, 9443 if s in keycloak else p) for s, p in rows["vendor_default_transport_source__port"]])
    provides = _derive(model, prog, label, changed)["provides"]
    assert ("idp", "identity", "9443") in provides and ("idp", "identity", "8443") not in provides

    # Without its port decision, the registry service listens where its maker's statement says.
    registry = {d for d, of in product.items() if of == "registry"}
    assert registry, "Missing the port decision for the registry"
    changed = {table: [row for row in values if row[0] not in registry]
               if table == DECISION or table.startswith(DECISION + "__") else values
               for table, values in rows.items()}
    default = {str(s["port"]) for s in statements if s["product"] == "registry"}
    assert default, "Missing the registry transport statement"
    reg = {row for row in _derive(model, prog, label, changed)["provides"] if row[0] == "reg"}
    assert reg == {("reg", "registry", p) for p in default}
