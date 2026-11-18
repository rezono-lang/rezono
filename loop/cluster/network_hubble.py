"""Trace a complete local Hubble sweep and retain its destination-side verdicts."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from queue import Empty, Queue
import subprocess
from threading import Thread
from time import monotonic


@dataclass(frozen=True)
class Flow:
    source: str
    destination: str
    port: int
    tick: int
    outcome: str
    event: dict


def _tick(value: str) -> int:
    stamp, _, fraction = value.rstrip("Z").partition(".")
    seconds = int(datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp())
    return seconds * 10**9 + int(fraction.ljust(9, "0"))


def _flow(row: dict) -> Flow | None:
    original = row.get("flow", {})
    direction = original.get("traffic_direction", original.get("trafficDirection"))
    ip = original.get("IP", {})
    tcp = original.get("l4", {}).get("TCP", {})
    port = tcp.get("destination_port", tcp.get("destinationPort"))
    verdict = original.get("verdict")
    if direction != "INGRESS" or not port or verdict not in {"FORWARDED", "DROPPED"}:
        return None
    return Flow(ip["source"], ip["destination"], port, _tick(original["time"]),
                "allow" if verdict == "FORWARDED" else "deny", row)


class Hubble:
    def __init__(self, command: list[str]):
        self.command = command
        self.rows: Queue[dict | Exception] = Queue()
        self.flows: list[Flow] = []

    def __enter__(self):
        self.process = subprocess.Popen(self.command, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        return self

    def __exit__(self, *exc):
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=8)
        self.reader.join(timeout=10)

    def _read(self) -> None:
        try:
            for line in self.process.stdout:
                self.rows.put(json.loads(line))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.rows.put(exc)
        finally:
            self.rows.put(RuntimeError("The Hubble stream ended"))

    def _receive(self, wait: float) -> None:
        try:
            row = self.rows.get(timeout=wait)
        except Empty:
            return
        if isinstance(row, Exception):
            raise row
        if "lost_events" in row or "lostEvents" in row:
            raise RuntimeError(f"Hubble reported dropped observations: {row}")
        flow = _flow(row)
        if flow is not None:
            self.flows.append(flow)

    def heartbeat(self, source: str, destination: str, port: int, after: int,
                  generate: Callable[[], None]) -> Flow:
        deadline = monotonic() + 18
        while monotonic() < deadline:
            generate()
            for _ in range(3):
                self._receive(0.5)
                matches = [flow for flow in self.flows if flow.tick > after
                           and (flow.source, flow.destination, flow.port) == (source, destination, port)]
                if matches:
                    return min(matches, key=lambda flow: flow.tick)
        raise RuntimeError("No destination-side Hubble heartbeat for the fixture node")

    def drain(self) -> None:
        # The heartbeat is ordered in the same node stream as its coverage.
        while not self.rows.empty():
            self._receive(0)
        if self.process.poll() is not None:
            raise RuntimeError("The Hubble collector disappeared during the sweep")
