"""nftables comment 127-byte UTF-8 ceiling and ManagementFence watch subprocess cleanup
(decisions/loop-apply-readback.md)."""

from __future__ import annotations

import io
from pathlib import Path
import re

import pytest

LOOP_ROOT = Path(__file__).resolve().parents[1]
NFT_QUOTED_COMMENT = re.compile(r'^"[^"\\\r\n]+"$')


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/loop-apply-readback.md: router_render nftables comments must fit within 127 UTF-8 bytes "
        "to respect libnftnl's NUL-terminated 128-byte buffer"
    ),
)
def test_router_render_nft_comments_fit_within_127_utf8_bytes(monkeypatch):
    monkeypatch.syspath_prepend(str(LOOP_ROOT))
    from router_render import render

    base_packet = {
        "sourceFrom": 3221225984,
        "sourceTo": 3221225999,
        "destinationAddress": 3325256711,
        "protocol": "TCP",
        "fromPort": 443,
        "toPort": 443,
    }
    rules = [
        # Control: short ASCII rule.
        {
            **base_packet,
            "source": "client",
            "destination": "gateway",
            "function": "ingress",
        },
        # Long ASCII names that currently saturate 128 UTF-8 bytes.
        {
            **base_packet,
            "source": "service-alpha-" + ("a" * 80),
            "destination": "gateway-beta-" + ("b" * 80),
            "function": "management-endpoint-" + ("c" * 40),
            "fromPort": 8443,
            "toPort": 8443,
        },
        # Multi-byte UTF-8 names (2-byte, 3-byte, and 4-byte codepoints) landing on the byte ceiling.
        {
            **base_packet,
            "source": "\u00e9" * 55 + "x",
            "destination": "gateway",
            "function": "sync",
            "fromPort": 9443,
            "toPort": 9443,
        },
        {
            **base_packet,
            "source": "\u20ac" * 37,
            "destination": "gateway-\U0001f9ed",
            "function": "replica",
            "fromPort": 9444,
            "toPort": 9444,
        },
    ]

    rendered = render(rules).decode("utf-8")
    accept_lines = [line for line in rendered.splitlines() if " accept comment " in line]
    assert len(accept_lines) == len(rules)

    for line in accept_lines:
        _, _, comment_token = line.partition(" accept comment ")
        assert NFT_QUOTED_COMMENT.fullmatch(comment_token), f"invalid quoted comment syntax: {comment_token!r}"
        inner = comment_token[1:-1]
        byte_len = len(inner.encode("utf-8"))
        assert byte_len <= 127, (
            f"nftables comment inner text is {byte_len} UTF-8 bytes (must be <= 127): {inner!r}"
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/loop-apply-readback.md: ManagementFence.__init__ must terminate/kill and reap its "
        "kubectl --watch subprocess if read_state fails or detects non-zero replicas"
    ),
)
def test_management_fence_terminates_watch_subprocess_if_init_guard_fails(monkeypatch):
    monkeypatch.syspath_prepend(str(LOOP_ROOT / "cluster"))
    import record_management_backup as rmb

    class FakeWatchProcess:
        def __init__(self, cmd: list[str]) -> None:
            self.cmd = cmd
            self.returncode: int | None = None
            self.terminated = False
            self.killed = False
            self.reaped = False
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")

        @property
        def stopped(self) -> bool:
            return self.terminated or self.killed

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            if self.returncode is None:
                self.returncode = -15

        def kill(self) -> None:
            self.killed = True
            if self.returncode is None:
                self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            self.reaped = True
            return 0 if self.returncode is None else self.returncode

        def communicate(self, input=None, timeout: float | None = None) -> tuple[str, str]:
            self.reaped = True
            if self.returncode is None:
                self.returncode = 0
            return "", ""

    class FakeCluster:
        def apply(self, manifest: dict) -> None:
            pass

        def namespaced(self, namespace: str, *args: str) -> list[str]:
            return ["kubectl", "-n", namespace, *args]

    spawned: list[FakeWatchProcess] = []

    def fake_popen(cmd, **kwargs):
        proc = FakeWatchProcess(list(cmd))
        spawned.append(proc)
        return proc

    monkeypatch.setattr(rmb, "_scale_down_management", lambda cluster: None)
    monkeypatch.setattr(rmb, "sleep", lambda seconds: None)
    monkeypatch.setattr(rmb.subprocess, "Popen", fake_popen)

    # Sanity control: clean initialization leaves watch running until close() kills and reaps it.
    monkeypatch.setattr(
        rmb.ManagementFence,
        "read_state",
        lambda self: {"replicas": 0, "ready_endpoints": []},
    )
    ok_fence = rmb.ManagementFence(FakeCluster(), "fence-ok")
    ok_proc = spawned[-1]
    assert ok_proc.poll() is None
    ok_fence.close()
    assert ok_proc.killed is True and ok_proc.reaped is True

    # Case A: read_state() raises RuntimeError during __init__.
    def raising_read_state(self):
        raise RuntimeError("apiserver unavailable during fence read_state")

    monkeypatch.setattr(rmb.ManagementFence, "read_state", raising_read_state)
    with pytest.raises(RuntimeError, match="apiserver unavailable during fence read_state"):
        rmb.ManagementFence(FakeCluster(), "fence-raise")
    proc_raise = spawned[-1]

    # Case B: read_state() finds replicas != 0 during __init__.
    monkeypatch.setattr(
        rmb.ManagementFence,
        "read_state",
        lambda self: {"replicas": 1, "ready_endpoints": []},
    )
    with pytest.raises(RuntimeError, match="not stopped under the fence"):
        rmb.ManagementFence(FakeCluster(), "fence-nonzero")
    proc_nonzero = spawned[-1]

    assert proc_raise.stopped and proc_raise.reaped, (
        f"watch subprocess leaked when read_state() raised: terminated={proc_raise.terminated}, "
        f"killed={proc_raise.killed}, reaped={proc_raise.reaped}"
    )
    assert proc_nonzero.stopped and proc_nonzero.reaped, (
        f"watch subprocess leaked when replicas != 0: terminated={proc_nonzero.terminated}, "
        f"killed={proc_nonzero.killed}, reaped={proc_nonzero.reaped}"
    )
