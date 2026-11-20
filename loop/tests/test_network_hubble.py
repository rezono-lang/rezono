"""Verify Hubble readiness waiting, startup retries, and fail-closed heartbeat checks."""

import importlib
import json
from pathlib import Path
import queue
import subprocess

import pytest


LOOP_DIR = Path(__file__).resolve().parents[1]
CLUSTER_DIR = LOOP_DIR / "cluster"


def _load(monkeypatch, name):
    monkeypatch.syspath_prepend(str(LOOP_DIR))
    monkeypatch.syspath_prepend(str(CLUSTER_DIR))
    return importlib.import_module(name)


def _flow_row(source: str, destination: str, port: int, timestamp: str,
              direction: str = "INGRESS", verdict: str = "FORWARDED") -> str:
    return json.dumps({
        "flow": {
            "time": timestamp,
            "traffic_direction": direction,
            "IP": {"source": source, "destination": destination},
            "l4": {"TCP": {"destination_port": port}},
            "verdict": verdict,
        }
    })


class _FakeStdout:
    """Line stream that yields preset lines and can optionally block until closed."""

    def __init__(self, lines: list[str], *, stay_open: bool = False):
        self._queue: queue.Queue[str | None] = queue.Queue()
        for line in lines:
            self._queue.put(line + "\n")
        self._stay_open = stay_open
        if not stay_open:
            self._queue.put(None)

    def push(self, line: str) -> None:
        self._queue.put(line + "\n")

    def close(self) -> None:
        self._queue.put(None)

    def __iter__(self):
        return self

    def __next__(self) -> str:
        item = self._queue.get()
        if item is None:
            raise StopIteration
        return item


class _FakePopen:
    def __init__(self, lines: list[str], *, stay_open: bool = False, exit_code: int = 1):
        self.stdout = _FakeStdout(lines, stay_open=stay_open)
        self._stay_open = stay_open
        self._exit_code = exit_code
        self._terminated = False

    def poll(self):
        if self._terminated or not self._stay_open:
            return 0 if self._terminated else self._exit_code
        return None

    def terminate(self) -> None:
        self._terminated = True
        self.stdout.close()

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout=None) -> int:
        self.stdout.close()
        return 0 if self._terminated else self._exit_code


def test_hubble_waits_for_relay_and_retries_transient_startup_eof(monkeypatch):
    network_hubble = _load(monkeypatch, "network_hubble")
    now = 0.0

    def clock() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        now += seconds

    readiness_states = iter([False, subprocess.CalledProcessError(1, "kubectl"), True])

    def readiness_check() -> bool:
        state = next(readiness_states)
        if isinstance(state, Exception):
            raise state
        return state

    launches = []

    def fake_popen(command, stdout=None, text=None, encoding=None):
        attempt = len(launches)
        if attempt == 0:
            proc = _FakePopen([], stay_open=False, exit_code=1)
        else:
            unrelated = [_flow_row("10.0.0.99", "10.0.0.88", 9999, "2026-01-01T00:00:02.000000000Z")
                         for _ in range(10)]
            proc = _FakePopen(unrelated, stay_open=True)
        launches.append(proc)
        return proc

    monkeypatch.setattr(network_hubble.subprocess, "Popen", fake_popen)

    probes = 0

    def generate() -> None:
        nonlocal probes
        probes += 1
        if len(launches) >= 2 and probes >= 2:
            launches[-1].stdout.push(
                _flow_row("10.0.0.1", "10.0.0.2", 8090, "2026-01-01T00:00:05.000000000Z")
            )

    hubble = network_hubble.Hubble(
        ["kubectl", "exec"],
        readiness_check=readiness_check,
        readiness_timeout=10.0,
        readiness_interval=1.0,
        heartbeat_timeout=10.0,
        poll_interval=0.05,
        retry_interval=0.5,
        clock=clock,
        sleeper=sleeper,
    )
    with hubble:
        assert now == 2.0
        assert len(launches) == 1
        before_tick = network_hubble._tick("2026-01-01T00:00:01.000000000Z")
        flow = hubble.heartbeat("10.0.0.1", "10.0.0.2", 8090, before_tick, generate)

    assert len(launches) == 2
    assert flow.source == "10.0.0.1"
    assert flow.destination == "10.0.0.2"
    assert flow.port == 8090
    assert flow.outcome == "allow"


def test_hubble_readiness_timeout_fails_closed(monkeypatch):
    network_hubble = _load(monkeypatch, "network_hubble")
    now = 0.0

    def clock() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        now += seconds

    launched = False

    def fake_popen(*args, **kwargs):
        nonlocal launched
        launched = True
        return _FakePopen([])

    monkeypatch.setattr(network_hubble.subprocess, "Popen", fake_popen)
    hubble = network_hubble.Hubble(
        ["kubectl", "exec"],
        readiness_check=lambda: False,
        readiness_timeout=3.0,
        readiness_interval=1.5,
        clock=clock,
        sleeper=sleeper,
    )
    with pytest.raises(RuntimeError, match="not ready"):
        with hubble:
            pass
    assert not launched
    assert now == 3.0


def test_hubble_absent_heartbeat_still_raises_fail_closed(monkeypatch):
    network_hubble = _load(monkeypatch, "network_hubble")
    now = 0.0

    def clock() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        now += seconds

    unrelated = _flow_row("10.0.0.99", "10.0.0.88", 9999, "2026-01-01T00:00:02.000000000Z")
    monkeypatch.setattr(
        network_hubble.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakePopen([unrelated], stay_open=True),
    )

    def generate() -> None:
        nonlocal now
        now += 1.0

    hubble = network_hubble.Hubble(
        ["kubectl", "exec"],
        heartbeat_timeout=3.0,
        poll_interval=0.01,
        clock=clock,
        sleeper=sleeper,
    )
    with hubble:
        before_tick = network_hubble._tick("2026-01-01T00:00:01.000000000Z")
        with pytest.raises(RuntimeError, match="No destination-side Hubble heartbeat"):
            hubble.heartbeat("10.0.0.1", "10.0.0.2", 8090, before_tick, generate)


def test_hubble_mid_sweep_stream_end_does_not_restart(monkeypatch):
    network_hubble = _load(monkeypatch, "network_hubble")
    now = 0.0
    launches = []

    def fake_popen(*args, **kwargs):
        proc = _FakePopen(
            [_flow_row("10.0.0.1", "10.0.0.2", 8090, "2026-01-01T00:00:02.000000000Z")],
            stay_open=False,
            exit_code=1,
        )
        launches.append(proc)
        return proc

    monkeypatch.setattr(network_hubble.subprocess, "Popen", fake_popen)

    hubble = network_hubble.Hubble(
        ["kubectl", "exec"],
        heartbeat_timeout=5.0,
        poll_interval=0.01,
        retry_interval=0.01,
        clock=lambda: now,
        sleeper=lambda s: None,
    )
    with hubble:
        after_tick = network_hubble._tick("2026-01-01T00:00:03.000000000Z")
        with pytest.raises(RuntimeError, match="The Hubble stream ended"):
            hubble.heartbeat("10.0.0.1", "10.0.0.2", 8090, after_tick, lambda: None)

    assert len(launches) == 1


def test_cluster_hubble_ready_checks_cilium_and_hubble_relay(monkeypatch):
    record_network = _load(monkeypatch, "record_network")
    cluster = object.__new__(record_network.Cluster)
    cases = [
        ({"status": {"numberReady": 1}}, {"status": {"readyReplicas": None}}, False),
        ({"status": {"numberReady": 1}}, {"status": {"readyReplicas": 0}}, False),
        ({"status": {"numberReady": 1}}, {"status": {"readyReplicas": 1}}, True),
    ]

    for cilium, relay, expected in cases:
        cluster.read = lambda kind_cmd, resource, name, namespace=None, c=cilium, r=relay: (
            c if name == "cilium" else r
        )
        assert cluster._hubble_ready() is expected
