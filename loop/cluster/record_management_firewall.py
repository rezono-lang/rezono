"""Apply intended router rules in an isolated netns, mutate, read back via nftables, and record drift."""

from __future__ import annotations

import hashlib
from ipaddress import IPv4Address, IPv4Network
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for _candidate in (ROOT, ROOT / "loop", ROOT / "loop" / "cluster"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from management_recorder import ManagementCluster
from rezono_compiler import batch, calc, facts, pack, rules
from router_preflight import validate
from router_render import PacketRule, render

ROUTER = "boundary"
TABLE = "rezono_fixture"
CHAIN = "forward"
SOURCE_NETWORK = IPv4Network("192.0.2.0/28")
DESTINATION_ADDRESS = IPv4Address("198.51.100.7")
PLATFORM_PACK = ROOT / "examples" / "platform"


def sudo(*args: str, data: str | None = None) -> str:
    """Run a non-interactive privileged network-namespace command."""
    return subprocess.run(
        ["sudo", "-n", *args],
        input=data,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        check=True,
        timeout=15,
    ).stdout


def _desired_rules() -> list[PacketRule]:
    """Return the validated intended TCP 443 and 8443 allowance records."""
    source_from = int(SOURCE_NETWORK.network_address)
    source_to = int(SOURCE_NETWORK.broadcast_address)
    destination = int(DESTINATION_ADDRESS)
    intended: list[PacketRule] = [
        {
            "source": "client",
            "destination": "gateway",
            "function": "ingress",
            "sourceFrom": source_from,
            "sourceTo": source_to,
            "destinationAddress": destination,
            "protocol": "TCP",
            "fromPort": 443,
            "toPort": 443,
        },
        {
            "source": "client",
            "destination": "gateway",
            "function": "management",
            "sourceFrom": source_from,
            "sourceTo": source_to,
            "destinationAddress": destination,
            "protocol": "TCP",
            "fromPort": 8443,
            "toPort": 8443,
        },
    ]
    validate(intended)
    return intended


def _nft_script(rendered: bytes) -> str:
    """Rewrite JSON witness comments into plain nftables comments without changing match clauses."""
    lines = []
    for line in rendered.decode("utf-8").split("\n"):
        expression, separator, witness = line.partition(" accept comment ")
        if separator:
            identity = hashlib.sha256(witness.encode("utf-8")).hexdigest()
            line = f'{expression} accept comment "rezono-allow-{identity}"'
        lines.append(line)
    return "\n".join(lines)


def _parse_ip_expr(value: object) -> tuple[int, int]:
    """Parse an nftables JSON IPv4 address, range, or prefix into inclusive integer bounds."""
    if isinstance(value, str):
        addr = int(IPv4Address(value))
        return addr, addr
    if isinstance(value, dict):
        if "range" in value and isinstance(value["range"], list) and len(value["range"]) == 2:
            lo, hi = value["range"]
            return int(IPv4Address(lo)), int(IPv4Address(hi))
        if "prefix" in value and isinstance(value["prefix"], dict):
            prefix = value["prefix"]
            network = IPv4Network(f"{prefix['addr']}/{prefix['len']}", strict=False)
            return int(network.network_address), int(network.broadcast_address)
    raise RuntimeError(f"Unsupported nftables IPv4 match expression: {value!r}")


def _parse_port_expr(value: object) -> tuple[int, int]:
    """Parse an nftables JSON port or port range into inclusive integer bounds."""
    if type(value) is int:
        return value, value
    if isinstance(value, dict) and "range" in value and isinstance(value["range"], list) and len(value["range"]) == 2:
        lo, hi = value["range"]
        if type(lo) is int and type(hi) is int:
            return lo, hi
    raise RuntimeError(f"Unsupported nftables port match expression: {value!r}")


def _parse_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Extract normalized allowance fields from a single nftables JSON rule object."""
    expressions = rule.get("expr")
    if not isinstance(expressions, list) or not any("accept" in item for item in expressions):
        raise RuntimeError(f"Unexpected non-accept rule in {TABLE}/{CHAIN}: {rule!r}")
    src_bounds: tuple[int, int] | None = None
    dst_bounds: tuple[int, int] | None = None
    protocol: str | None = None
    port_bounds: tuple[int, int] | None = None
    for item in expressions:
        match = item.get("match")
        if not match:
            continue
        if match.get("op") != "==":
            raise RuntimeError(f"Unsupported nftables match operator in {rule!r}")
        payload = (match.get("left") or {}).get("payload") or {}
        proto = payload.get("protocol")
        field = payload.get("field")
        right = match.get("right")
        if proto == "ip" and field == "saddr":
            src_bounds = _parse_ip_expr(right)
        elif proto == "ip" and field == "daddr":
            dst_bounds = _parse_ip_expr(right)
        elif proto in ("tcp", "udp") and field == "dport":
            protocol = proto.upper()
            port_bounds = _parse_port_expr(right)
    if src_bounds is None or dst_bounds is None or protocol is None or port_bounds is None:
        raise RuntimeError(f"Incomplete nftables rule fields in {rule!r}")
    if dst_bounds[0] != dst_bounds[1]:
        raise RuntimeError(f"Expected single destination address in {rule!r}")
    handle = rule.get("handle")
    if type(handle) is not int:
        raise RuntimeError(f"Missing kernel handle on nftables rule {rule!r}")
    return {
        "handle": handle,
        "sourceFrom": src_bounds[0],
        "sourceTo": src_bounds[1],
        "destinationAddress": dst_bounds[0],
        "protocol": protocol,
        "fromPort": port_bounds[0],
        "toPort": port_bounds[1],
    }


def _parse_nft_table(payload: str) -> tuple[bool, list[dict[str, Any]]]:
    """Parse `nft -j list table ip rezono_fixture` and verify table/chain completeness."""
    document = json.loads(payload)
    items = document.get("nftables")
    if not isinstance(items, list):
        raise RuntimeError("Missing nftables list in nft -j output")
    has_table = False
    has_chain = False
    seen_rules: list[dict[str, Any]] = []
    for item in items:
        if "table" in item:
            table = item["table"]
            if table.get("family") == "ip" and table.get("name") == TABLE:
                has_table = True
        elif "chain" in item:
            chain = item["chain"]
            if (
                chain.get("family") == "ip"
                and chain.get("table") == TABLE
                and chain.get("name") == CHAIN
                and chain.get("type") == "filter"
                and chain.get("hook") == "forward"
                and chain.get("policy") == "drop"
            ):
                has_chain = True
        elif "rule" in item:
            rule = item["rule"]
            if rule.get("family") == "ip" and rule.get("table") == TABLE and rule.get("chain") == CHAIN:
                seen_rules.append(_parse_rule(rule))
    if not (has_table and has_chain):
        raise RuntimeError(f"Incomplete nftables readback for ip/{TABLE}/{CHAIN}")
    return True, seen_rules


def _apply_and_readback(netns: str, rendered: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Apply rendered rules in an isolated netns, drop 8443, add 9443, and read back the full table."""
    sudo("ip", "netns", "add", netns)
    try:
        sudo("ip", "netns", "exec", netns, "nft", "-f", "-", data=_nft_script(rendered))
        initial_raw = sudo("ip", "netns", "exec", netns, "nft", "-j", "list", "table", "ip", TABLE)
        _, initial_rules = _parse_nft_table(initial_raw)
        handles_8443 = [
            rule["handle"]
            for rule in initial_rules
            if rule["protocol"] == "TCP" and rule["fromPort"] == 8443 and rule["toPort"] == 8443
        ]
        if len(handles_8443) != 1:
            raise RuntimeError(f"Expected one TCP 8443 rule before mutation, found {initial_rules!r}")
        sudo(
            "ip",
            "netns",
            "exec",
            netns,
            "nft",
            "delete",
            "rule",
            "ip",
            TABLE,
            CHAIN,
            "handle",
            str(handles_8443[0]),
        )
        source_range = f"{SOURCE_NETWORK.network_address}-{SOURCE_NETWORK.broadcast_address}"
        sudo(
            "ip",
            "netns",
            "exec",
            netns,
            "nft",
            "add",
            "rule",
            "ip",
            TABLE,
            CHAIN,
            "ip",
            "saddr",
            source_range,
            "ip",
            "daddr",
            str(DESTINATION_ADDRESS),
            "tcp",
            "dport",
            "9443",
            "accept",
            "comment",
            '"rezono-extra-9443"',
        )
        raw_table = sudo("ip", "netns", "exec", netns, "nft", "-j", "list", "table", "ip", TABLE)
        complete, seen_rules = _parse_nft_table(raw_table)
        if not complete:
            raise RuntimeError("Router table readback was not complete")
        return raw_table, seen_rules
    finally:
        sudo("ip", "netns", "del", netns)


def _format_source(rule: dict[str, Any]) -> str:
    start = IPv4Address(rule["sourceFrom"])
    end = IPv4Address(rule["sourceTo"])
    return str(start) if start == end else f"{start}-{end}"


def _fact_row(identifier: str, run_id: str, rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": identifier,
        "run": run_id,
        "router": ROUTER,
        "table": TABLE,
        "source": _format_source(rule),
        "destination": str(IPv4Address(rule["destinationAddress"])),
        "protocol": rule["protocol"],
        "first_port": rule["fromPort"],
        "last_port": rule["toPort"],
    }


def _rule_key(rule: dict[str, Any]) -> list[Any]:
    return [
        rule["sourceFrom"],
        rule["sourceTo"],
        rule["destinationAddress"],
        rule["protocol"],
        rule["fromPort"],
        rule["toPort"],
    ]


def _evaluate_firewall_dl(
    run_id: str,
    complete: bool,
    desired_rules: list[PacketRule],
    seen_rules: list[dict[str, Any]],
) -> list[tuple[str, list[Any], str, str]]:
    """Evaluate drift through examples/platform/rules/management_firewall.dl."""
    desired_by_id = {f"desired-{index}": dict(rule) for index, rule in enumerate(desired_rules, 1)}
    seen_by_id = {f"seen-{index}-handle-{rule['handle']}": rule for index, rule in enumerate(seen_rules, 1)}
    records = {
        "router_management": [{"id": "active-policy", "run": run_id, "router": ROUTER, "table": TABLE}],
        "router_sweep": [{"id": "complete-read", "run": run_id, "router": ROUTER, "table": TABLE, "complete": complete}],
        "router_desired": [_fact_row(identifier, run_id, rule) for identifier, rule in desired_by_id.items()],
        "router_seen": [_fact_row(identifier, run_id, rule) for identifier, rule in seen_by_id.items()],
    }
    model = pack.read(PLATFORM_PACK)
    program = rules.load(model.rules)
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    con, _, _ = batch.run(model, program, facts.rows_of(model, records), calculation)
    try:
        derived = batch.read(con, program, ["managed_router_drift", "managed_router_unknown"])
    finally:
        con.close()
    unknown = derived.get("managed_router_unknown", set())
    if unknown:
        raise RuntimeError(f"management_firewall.dl reported unknown scope: {sorted(unknown)}")
    findings = []
    for direction, allowance_id, sweep_id in sorted(derived.get("managed_router_drift", set())):
        source_map = desired_by_id if direction == "missing" else seen_by_id
        if allowance_id not in source_map:
            raise RuntimeError(f"Unexpected drift allowance {allowance_id!r} for direction {direction!r}")
        findings.append((direction, _rule_key(source_map[allowance_id]), allowance_id, sweep_id))
    return findings


def main() -> None:
    cluster = ManagementCluster()
    desired_rules = _desired_rules()
    rendered = render(desired_rules)
    desired_event = cluster.make_event(
        "firewall",
        "desired-router-publication",
        router=ROUTER,
        table=TABLE,
        rules=desired_rules,
        applied_sha256=hashlib.sha256(rendered).hexdigest(),
    )
    netns = f"rzfw-{cluster.run}-{cluster.attempt}"
    raw_table, seen_rules = _apply_and_readback(netns, rendered)
    read_event = cluster.make_event(
        "firewall",
        "complete-router-read",
        router=ROUTER,
        table=TABLE,
        complete=True,
        rules=seen_rules,
        table_sha256=hashlib.sha256(raw_table.encode("utf-8")).hexdigest(),
    )
    drift_rows = _evaluate_firewall_dl(cluster.run, True, desired_rules, seen_rules)
    if {row[0] for row in drift_rows} != {"missing", "extra"} or len(drift_rows) != 2:
        raise RuntimeError(f"Expected one missing and one extra drift row, got {drift_rows!r}")
    drift_events = [
        cluster.make_event(
            "firewall",
            "router-drift",
            router=ROUTER,
            table=TABLE,
            direction=direction,
            allowance=allowance_id,
            sweep=sweep_id,
            rule=rule_key,
            source_evidence=[desired_event["evidence"], read_event["evidence"]],
        )
        for direction, rule_key, allowance_id, sweep_id in drift_rows
    ]
    cluster.record_job("firewall", [desired_event, read_event, *drift_events])


if __name__ == "__main__":
    main()
