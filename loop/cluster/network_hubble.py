"""Trace a complete local Hubble sweep and retain its destination-side verdicts."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from queue import Empty, Queue
import subprocess
from threading import Thread
from time import monotonic, sleep


class _StreamEnded(RuntimeError):
    """Internal marker for EOF on the Hubble collector stream."""


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
    def __init__(
        self,
        command: list[str],
        *,
        readiness_check: Callable[[], bool] | None = None,
        readiness_timeout: float = 90.0,
        readiness_interval: float = 2.0,
        heartbeat_timeout: float = 30.0,
        poll_interval: float = 0.5,
        retry_interval: float = 1.0,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ):
        self.command = command
        self.readiness_check = readiness_check
        self.readiness_timeout = readiness_timeout
        self.readiness_interval = readiness_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.poll_interval = poll_interval
        self.retry_interval = retry_interval
        self._clock = clock
        self._sleeper = sleeper
        self.rows: Queue[dict | Exception] = Queue()
        self.flows: list[Flow] = []
        self.process: subprocess.Popen | None = None
        self.reader: Thread | None = None
        self._stream_started = False

    def wait_ready(self) -> None:
        if self.readiness_check is None:
            return
        deadline = self._clock() + self.readiness_timeout
        while True:
            try:
                if self.readiness_check():
                    return
            except (subprocess.SubprocessError, OSError):
                pass
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise RuntimeError("Hubble is not ready before starting the sweep")
            self._sleeper(min(self.readiness_interval, remaining))

    def _start_process(self) -> None:
        self.rows = Queue()
        self._stream_started = False
        self.process = subprocess.Popen(self.command, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()

    def _stop_process(self) -> None:
        process, reader = self.process, self.reader
        self.process = None
        self.reader = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=8)
            else:
                process.wait(timeout=8)
        if reader is not None:
            reader.join(timeout=10)
        if process is not None and process.stdout is not None:
            process.stdout.close()

    def __enter__(self):
        self.wait_ready()
        self._start_process()
        return self

    def __exit__(self, *exc):
        self._stop_process()

    def _read(self) -> None:
        try:
            for line in self.process.stdout:
                self.rows.put(json.loads(line))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.rows.put(exc)
        finally:
            self.rows.put(_StreamEnded("The Hubble stream ended"))

    def _receive(self, wait: float) -> None:
        try:
            row = self.rows.get(timeout=wait)
        except Empty:
            return
        if isinstance(row, Exception):
            raise row
        self._stream_started = True
        if "lost_events" in row or "lostEvents" in row:
            raise RuntimeError(f"Hubble reported dropped observations: {row}")
        flow = _flow(row)
        if flow is not None:
            self.flows.append(flow)

    def _drain_available(self) -> None:
        while not self.rows.empty():
            self._receive(0)

    def _restart(self, deadline: float) -> bool:
        self._stop_process()
        remaining = deadline - self._clock()
        if remaining <= 0:
            return False
        delay = min(self.retry_interval, remaining)
        if delay > 0:
            self._sleeper(delay)
            if self._clock() >= deadline:
                return False
        self._start_process()
        return True

    def _recover_startup_eof(self, exc: _StreamEnded, deadline: float) -> RuntimeError:
        if self._stream_started:
            raise RuntimeError(str(exc)) from exc
        error = RuntimeError(str(exc))
        if not self._restart(deadline):
            raise error from exc
        return error

    def heartbeat(self, source: str, destination: str, port: int, after: int,
                  generate: Callable[[], None]) -> Flow:
        deadline = self._clock() + self.heartbeat_timeout
        last_error: RuntimeError | None = None
        while self._clock() < deadline:
            if self.process is None:
                if not self._restart(deadline):
                    break
            elif not self._stream_started and self.process.poll() is not None:
                try:
                    self._drain_available()
                except _StreamEnded as exc:
                    last_error = self._recover_startup_eof(exc, deadline)
                else:
                    if not self._stream_started and not self._restart(deadline):
                        break
            generate()
            restarted = False
            for _ in range(3):
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                try:
                    self._receive(min(self.poll_interval, remaining))
                    self._drain_available()
                except _StreamEnded as exc:
                    last_error = self._recover_startup_eof(exc, deadline)
                    restarted = True
                    break
                matches = [flow for flow in self.flows if flow.tick > after
                           and (flow.source, flow.destination, flow.port) == (source, destination, port)]
                if matches:
                    return min(matches, key=lambda flow: flow.tick)
            if not restarted:
                last_error = None
        if last_error is not None and not self._stream_started:
            raise last_error
        raise RuntimeError("No destination-side Hubble heartbeat for the fixture node")

    def drain(self) -> None:
        # The heartbeat is ordered in the same node stream as its coverage.
        self._drain_available()
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("The Hubble collector disappeared during the sweep")
