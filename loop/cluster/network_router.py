"""Isolated nftables transit for the disposable network fixture."""

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
import hashlib
from ipaddress import IPv4Address, IPv4Network
import json
import subprocess

from router_preflight import validate
from router_render import render


CLIENT = IPv4Network("192.0.2.0/28")
TRANSIT = IPv4Network("198.51.100.0/30")
DENY = "rezono-default-drop"


def sudo(*args: str, data: str | None = None) -> str:
    return subprocess.run(["sudo", "-n", *args], input=data, text=True,
                          stdout=subprocess.PIPE, check=True, timeout=15).stdout


class Router:
    def __init__(self, name: str, clients: dict[str, str]):
        self.name = name
        self.clients = clients

    def counters(self) -> dict[str, int]:
        payload = sudo("ip", "netns", "exec", self.name, "nft", "-j", "list", "chain",
                       "ip", "rezono_fixture", "forward")
        counters = {}
        for item in json.loads(payload)["nftables"]:
            rule = item.get("rule", {})
            for expression in rule.get("expr", []):
                if "counter" in expression:
                    counters[rule["comment"]] = expression["counter"]["packets"]
        if DENY not in counters:
            raise RuntimeError("The nftables default drop counter is missing")
        return counters

    def verdict(self, before: dict[str, int]) -> tuple[str, str, int, int]:
        after = self.counters()
        if after.keys() != before.keys():
            raise RuntimeError("The nftables rules changed during the probe")
        hits = [rule for rule in after if after[rule] > before[rule]]
        if len(hits) != 1:
            raise RuntimeError(f"Expected exactly one observed router rule, found {hits}")
        rule, = hits
        return ("deny" if rule == DENY else "allow", rule, before[rule], after[rule])


def _rules(matrix: dict, destinations: dict[str, str]) -> str:
    validate(matrix["rules"])
    synthetic = {
        address["address"]: int(IPv4Address(destinations[endpoint]))
        for endpoint, address in matrix["endpoints"].items() if endpoint in destinations
    }
    actual_rules = [
        {**rule, "destinationAddress": synthetic[rule["destinationAddress"]]}
        for rule in matrix["rules"]
    ]
    # The offline artifact keeps the logical witness as JSON. Use a simple
    # nftables comment here because nft's scanner cannot read its escaped quotes.
    lines = []
    for line in render(actual_rules).decode().split("\n"):
        expression, separator, witness = line.partition(" accept comment ")
        if separator:
            identity = hashlib.sha256(witness.encode()).hexdigest()
            line = f'{expression} counter accept comment "rezono-allow-{identity}"'
        lines.append(line)
    text = "\n".join(lines)
    route = "        type filter hook forward priority filter; policy drop;"
    text = text.replace(route, route + "\n        ct state { established, related } accept", 1)
    text = text.replace("\n    }\n}", f'\n        counter drop comment "{DENY}"\n    }}\n}}', 1)
    translations = [
        f"        ip daddr {IPv4Address(old)} dnat to {IPv4Address(new)}"
        for old, new in sorted(synthetic.items())
    ]
    return text + "\n".join([
        "table ip rezono_fixture_nat {",
        "    chain ingress {",
        "        type nat hook prerouting priority dstnat; policy accept;",
        *translations,
        "    }",
        "}",
        "",
    ])


def _ip(namespace: str, *args: str) -> None:
    sudo("ip", "-n", namespace, *args)


def _link(namespace: str, name: str, other: str, peer: str) -> None:
    _ip(namespace, "link", "add", name, "type", "veth", "peer", "name", peer, "netns", other)
    _ip(namespace, "link", "set", name, "up")
    _ip(other, "link", "set", peer, "up")


@contextmanager
def transit(prefix: str, node: str, matrix: dict, destinations: dict[str, str],
            node_pid: Callable[[str], str]) -> Iterator[Router]:
    """Attach only an isolated transit link to the kind node and remove it on exit."""
    source_networks = {
        name: IPv4Address(data["address"])
        for name, data in matrix["endpoints"].items() if name not in destinations
    }
    if not source_networks or any(address not in CLIENT for address in source_networks.values()):
        raise ValueError("The fixture clients must use the dedicated documentation network")
    if any(IPv4Address(data["address"]) not in IPv4Network("192.0.2.16/28")
           for name, data in matrix["endpoints"].items() if name in destinations):
        raise ValueError("The fixture services must use the dedicated documentation network")
    router, fixture_node = f"{prefix}-router", f"{prefix}-node"
    link = "rz-net-fixture"
    with ExitStack() as stack:
        sudo("ip", "netns", "add", router)
        stack.callback(sudo, "ip", "netns", "del", router)
        sudo("ip", "netns", "attach", fixture_node, node_pid(node))
        stack.callback(sudo, "ip", "netns", "del", fixture_node)
        _link(router, "transit", fixture_node, link)
        stack.callback(_ip, router, "link", "del", "transit")
        _ip(router, "address", "add", f"{TRANSIT[1]}/{TRANSIT.prefixlen}", "dev", "transit")
        _ip(fixture_node, "address", "add", f"{TRANSIT[2]}/{TRANSIT.prefixlen}", "dev", link)
        _ip(fixture_node, "route", "add", str(CLIENT), "via", str(TRANSIT[1]), "dev", link)
        for destination in destinations.values():
            _ip(router, "route", "add", f"{IPv4Address(destination)}/32",
                "via", str(TRANSIT[2]), "dev", "transit")
        _ip(router, "link", "add", "clients", "type", "bridge")
        _ip(router, "address", "add", f"{CLIENT[14]}/{CLIENT.prefixlen}", "dev", "clients")
        _ip(router, "link", "set", "clients", "up")
        sudo("ip", "netns", "exec", router, "sysctl", "-w", "net.ipv4.ip_forward=1")

        clients = {}
        for index, (name, address) in enumerate(sorted(source_networks.items())):
            client = f"{prefix}-client{index}"
            clients[name] = client
            sudo("ip", "netns", "add", client)
            stack.callback(sudo, "ip", "netns", "del", client)
            port = f"client{index}"
            _link(router, port, client, "eth0")
            _ip(router, "link", "set", port, "master", "clients")
            _ip(client, "link", "set", "lo", "up")
            _ip(client, "address", "add", f"{address}/{CLIENT.prefixlen}", "dev", "eth0")
            _ip(client, "route", "add", "192.0.2.16/28", "via", str(CLIENT[14]), "dev", "eth0")
        sudo("ip", "netns", "exec", router, "nft", "-f", "-", data=_rules(matrix, destinations))
        yield Router(router, clients)
