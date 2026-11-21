"""Verify router_render emits valid nftables comments directly and the firewall recorder applies exact rendered bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
NFT_QUOTED_COMMENT = re.compile(r'^"[^"\\\r\n]+"$')


def _sample_rules() -> list[dict[str, object]]:
    return [
        {
            "source": "client",
            "destination": "gateway",
            "function": "ingress",
            "sourceFrom": 3221225984,
            "sourceTo": 3221225999,
            "destinationAddress": 3325256711,
            "protocol": "TCP",
            "fromPort": 443,
            "toPort": 443,
        },
        {
            "source": "client",
            "destination": "gateway",
            "function": "management",
            "sourceFrom": 3221225984,
            "sourceTo": 3221225999,
            "destinationAddress": 3325256711,
            "protocol": "TCP",
            "fromPort": 8443,
            "toPort": 8443,
        },
    ]


def _nft_table_json(ports: list[int]) -> str:
    items: list[dict[str, object]] = [
        {"table": {"family": "ip", "name": "rezono_fixture"}},
        {
            "chain": {
                "family": "ip",
                "table": "rezono_fixture",
                "name": "forward",
                "type": "filter",
                "hook": "forward",
                "policy": "drop",
            },
        },
    ]
    for handle, port in enumerate(ports, 1):
        items.append({
            "rule": {
                "family": "ip",
                "table": "rezono_fixture",
                "chain": "forward",
                "handle": handle,
                "expr": [
                    {"match": {"op": "==", "left": {"payload": {"protocol": "ip", "field": "saddr"}},
                               "right": {"range": ["192.0.2.0", "192.0.2.15"]}}},
                    {"match": {"op": "==", "left": {"payload": {"protocol": "ip", "field": "daddr"}},
                               "right": "198.51.100.7"}},
                    {"match": {"op": "==", "left": {"payload": {"protocol": "tcp", "field": "dport"}},
                               "right": port}},
                    {"accept": None},
                ],
            },
        })
    return json.dumps({"nftables": items})


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M2: decisions/loop-apply-readback.md: loop/router_render.py must emit valid nftables "
        "comment syntax directly without escaped quotes, and loop/cluster/record_management_firewall.py "
        "must apply the exact rendered script bytes to `nft -f -` without rewriting comments so "
        "`applied_sha256` equals the hash of the applied bytes (see decisions/platform-management-firewall.md)."
    ),
)
def test_router_render_emits_valid_nft_comments_and_recorder_applies_exact_bytes(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "loop" / "cluster"))
    monkeypatch.syspath_prepend(str(ROOT / "loop"))
    import record_management_firewall as rmf
    from router_render import render

    rules = _sample_rules()
    rendered = render(rules)

    # Counter-case: router_render produces deterministic LF-only UTF-8 output with policy drop and keeps
    # distinct logical witnesses separated even when packet fields are identical.
    assert isinstance(rendered, bytes)
    assert rendered.endswith(b"\n") and b"\r" not in rendered
    assert render(list(reversed(rules))) == rendered
    duplicate_packet = [rules[0], {**rules[0], "function": "audit"}]
    dup_accept_lines = [line for line in render(duplicate_packet).decode("utf-8").splitlines() if " accept comment " in line]
    assert len(dup_accept_lines) == 2

    # 1. Every `accept comment` clause emitted by router_render.render() must be valid nftables comment syntax
    #    (a plain double-quoted string with no backslash-escaped quotes `\"` and within nftables' 128-byte limit).
    text = rendered.decode("utf-8")
    accept_lines = [line for line in text.splitlines() if " accept comment " in line]
    assert len(accept_lines) == len(rules)
    for line in accept_lines:
        _, _, comment_token = line.partition(" accept comment ")
        assert '\\"' not in comment_token, f"router_render emitted escaped quotes invalid in nftables: {line!r}"
        assert NFT_QUOTED_COMMENT.fullmatch(comment_token), (
            f"router_render emitted invalid nftables quoted comment syntax: {comment_token!r}"
        )
        assert len(comment_token[1:-1].encode("utf-8")) <= 128, (
            f"router_render comment exceeds nftables 128-byte limit: {comment_token!r}"
        )

    if shutil.which("nft"):
        check = subprocess.run(
            ["nft", "-c", "-f", "-"],
            input=text,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=15,
        )
        if check.returncode != 0 and not any(
            msg in check.stderr for msg in ("Operation not permitted", "Permission denied")
        ):
            raise AssertionError(f"nft -c -f - rejected router_render.render() output:\n{check.stderr}\n{text}")

    # 2. loop/cluster/record_management_firewall.py must feed the exact rendered bytes to `nft -f -` without
    #    rewriting comments, so `applied_sha256` matches the SHA-256 of the script applied to nftables.
    applied_scripts: list[str] = []
    recorded_events: list[dict[str, object]] = []
    list_calls = 0

    class FakeCluster:
        run = "test-run"
        attempt = "1"

        def make_event(self, group: str, kind: str, **fields: object) -> dict[str, object]:
            return {"group": group, "kind": kind, "evidence": f"ev-{kind}", **fields}

        def record_job(self, group: str, events: list[dict[str, object]]) -> None:
            recorded_events.extend(events)

    def fake_sudo(*args: str, data: str | None = None) -> str:
        nonlocal list_calls
        if args[-3:] == ("nft", "-f", "-"):
            assert data is not None
            applied_scripts.append(data)
            return ""
        if args[-4:] == ("list", "table", "ip", rmf.TABLE):
            list_calls += 1
            return _nft_table_json([443, 8443] if list_calls == 1 else [443, 9443])
        return ""

    monkeypatch.setattr(rmf, "ManagementCluster", FakeCluster)
    monkeypatch.setattr(rmf, "sudo", fake_sudo)
    monkeypatch.setattr(
        rmf,
        "_evaluate_firewall_dl",
        lambda run_id, complete, desired, seen: [
            ("missing", [3221225984, 3221225999, 3325256711, "TCP", 8443, 8443], "desired-2", "complete-read"),
            ("extra", [3221225984, 3221225999, 3325256711, "TCP", 9443, 9443], "seen-2-handle-2", "complete-read"),
        ],
    )

    rmf.main()

    assert len(applied_scripts) == 1
    applied_bytes = applied_scripts[0].encode("utf-8")
    desired_events = [e for e in recorded_events if e["kind"] == "desired-router-publication"]
    assert len(desired_events) == 1
    expected_rendered = render(rmf._desired_rules())
    assert applied_bytes == expected_rendered, (
        "record_management_firewall rewrote router_render output before feeding it to `nft -f -`"
    )
    assert desired_events[0]["applied_sha256"] == hashlib.sha256(applied_bytes).hexdigest()
