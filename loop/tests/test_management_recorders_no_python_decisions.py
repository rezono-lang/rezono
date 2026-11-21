"""Strict M2 red tests requiring live management recorders to let pack rules decide.

Decisions:
- decisions/code-does-not-decide.md
- decisions/cluster-test-evidence.md
- decisions/platform-management-certificates.md
- decisions/platform-management-health.md
- decisions/platform-management-backup.md
- decisions/platform-management-access.md
- decisions/platform-management-firewall.md
- decisions/witnessed-read-completeness.md

Every test runs offline without kind against lightweight in-memory fakes and asserts on
the exact relation rows read through `rezono_compiler.batch.read` and the structured
observations recorded by each recorder.
"""

from __future__ import annotations

import ast
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import ssl
from time import time_ns
from types import ModuleType
from typing import Any
import urllib.error
import urllib.request

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CLUSTER_DIR = ROOT / "loop" / "cluster"
PLATFORM_PACK = ROOT / "examples" / "platform"
PLATFORM_PACK_NAME = yaml.safe_load((PLATFORM_PACK / "pack.yaml").read_text(encoding="utf-8"))["name"]
PROOF_CASES_DIR = PLATFORM_PACK / "proof_cases"

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ensure_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    for candidate in (ROOT, ROOT / "loop", CLUSTER_DIR, ROOT / "examples", PROOF_CASES_DIR):
        monkeypatch.syspath_prepend(str(candidate))


def _load_recorder(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    *,
    fake_cluster_cls: type,
    fake_run: Any | None = None,
    fake_sudo: Any | None = None,
) -> ModuleType:
    """Import a recorder script cleanly with ManagementCluster and shell helpers patched."""
    _ensure_paths(monkeypatch)
    import management_recorder

    monkeypatch.setattr(management_recorder, "ManagementCluster", fake_cluster_cls)
    if fake_run is not None:
        monkeypatch.setattr(management_recorder, "run", fake_run)

    path = CLUSTER_DIR / filename
    spec = importlib.util.spec_from_file_location(f"test_loaded_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if fake_run is not None and hasattr(module, "run"):
        monkeypatch.setattr(module, "run", fake_run)
    if fake_sudo is not None and hasattr(module, "sudo"):
        monkeypatch.setattr(module, "sudo", fake_sudo)
    if hasattr(module, "ManagementCluster"):
        monkeypatch.setattr(module, "ManagementCluster", fake_cluster_cls)
    return module


def _capture_batch_reads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    extra_relations: tuple[str, ...] = (),
    on_read: Any | None = None,
) -> tuple[set[tuple[str, str]], list[dict[str, set[tuple[str, ...]]]]]:
    """Capture `(pack, relation)` reads and exact relation snapshots through `rezono_compiler.batch.read`."""
    from rezono_compiler import batch

    seen: set[tuple[str, str]] = set()
    snapshots: list[dict[str, set[tuple[str, ...]]]] = []
    real_read = batch.read

    def wrapped_read(con: Any, prog: Any, names: Any = None) -> dict[str, set[tuple[str, ...]]]:
        rows = real_read(con, prog, names)
        for rel in rows:
            seen.add((prog.pack, rel))
        snapshot: dict[str, set[tuple[str, ...]]] = {rel: set(vals) for rel, vals in rows.items()}
        missing = [rel for rel in extra_relations if rel not in snapshot and rel in prog.relations]
        if missing:
            for rel, vals in real_read(con, prog, missing).items():
                snapshot[rel] = set(vals)
        snapshots.append(snapshot)
        if on_read is not None:
            on_read(prog.pack, names, snapshot)
        return rows

    monkeypatch.setattr(batch, "read", wrapped_read)
    return seen, snapshots


class _BaseFakeCluster:
    """Minimal in-memory stand-in for management_recorder.ManagementCluster."""

    def __init__(self, temp: Path, run_id: str = "404", attempt: str = "1") -> None:
        self.run = run_id
        self.attempt = attempt
        self.temp = temp
        self.temp.mkdir(parents=True, exist_ok=True)
        self.kubeconfig = temp / "fixture.kubeconfig"
        self.kubeconfig.write_text("{}", encoding="utf-8")
        self.server = "https://127.0.0.1:6443"
        self.command = ["kubectl", "--kubeconfig", str(self.kubeconfig), "--context", "kind-rezono-fixture"]
        self.node = "rezono-fixture-control-plane"
        self._last_tick_us = 0
        self.applied: list[dict[str, Any]] = []
        self.deleted: list[tuple[tuple[str, ...], str | None]] = []
        self.reads: list[tuple[tuple[str, ...], str | None]] = []
        self.recorded_jobs: list[tuple[str, list[dict[str, Any]]]] = []

    def namespaced(self, namespace: str, *args: str) -> list[str]:
        return [*self.command, "-n", namespace, *args]

    def read(self, *args: str, namespace: str | None = None, limit: int = 30) -> dict[str, Any]:
        self.reads.append((args, namespace))
        return {}

    def apply(self, manifest: dict[str, Any], limit: int = 30) -> None:
        self.applied.append(manifest)

    def delete(self, *args: str, namespace: str | None = None, limit: int = 45) -> None:
        self.deleted.append((args, namespace))

    def wait(self, *args: str, namespace: str | None = None, limit: int = 90) -> None:
        return None

    def ensure_namespace(self, name: str, labels: dict[str, str] | None = None) -> None:
        self.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name, "labels": labels or {}}})

    def build_go_image(self, source_path: Path, image: str, binary_name: str) -> None:
        return None

    def ensure_recorder_image(self) -> None:
        return None

    def next_observed_at(self) -> str:
        now_us = time_ns() // 1000
        if now_us <= self._last_tick_us:
            now_us = self._last_tick_us + 1
        self._last_tick_us = now_us
        seconds, micros = divmod(now_us, 1_000_000)
        stamp = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return f"{stamp}.{micros:06d}Z"

    def make_event(self, feature: str, kind: str, **fields: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run": self.run,
            "attempt": self.attempt,
            "feature": feature,
            "kind": kind,
            "observed_at": self.next_observed_at(),
            **fields,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return {**payload, "evidence": f"sha256:{digest}"}

    def record_job(self, feature: str, events: list[dict[str, Any]]) -> str:
        self.recorded_jobs.append((feature, list(events)))
        return f"fake-job-uid-{feature}"


def _platform_fact_rows() -> dict[str, list[dict[str, Any]]]:
    """Read authored fact YAML files under examples/platform/facts/ (excluding .sources.yaml)."""
    merged: dict[str, list[dict[str, Any]]] = {}
    facts_dir = PLATFORM_PACK / "facts"
    for path in sorted(facts_dir.glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for kind, rows in doc.items():
            if isinstance(rows, list):
                merged.setdefault(kind, []).extend(r for r in rows if isinstance(r, dict))
    return merged


def _dict_literal_int_values(tree: ast.AST, key_name: str) -> list[int]:
    """Return integer constants assigned directly to literal `key_name` in dict literals."""
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == key_name
                    and isinstance(value, ast.Constant)
                    and type(value.value) is int
                ):
                    found.append(value.value)
    return found


def _dict_literal_bool_values(tree: ast.AST, key_name: str) -> list[bool]:
    """Return boolean constants assigned directly to literal `key_name` in dict literals."""
    found: list[bool] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == key_name
                    and isinstance(value, ast.Constant)
                    and type(value.value) is bool
                ):
                    found.append(value.value)
    return found


def _make_event_keyword_literals(tree: ast.AST, kw_name: str) -> list[ast.AST]:
    """Return AST value nodes passed to `make_event(..., <kw_name>=<value>)`."""
    values: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "make_event":
            for kw in node.keywords:
                if kw.arg == kw_name:
                    values.append(kw.value)
    return values


def _is_int_literal(node: ast.AST, target: int) -> bool:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value == target
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) is int
    ):
        return -node.operand.value == target
    return False


def _event_row_tuples(event: dict[str, Any]) -> set[tuple[str, ...]]:
    """Extract structured string-row tuples from list-of-lists fields of a recorded event."""
    found: set[tuple[str, ...]] = set()
    for value in event.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (list, tuple)) and all(isinstance(part, str) for part in item):
                    found.add(tuple(item))
    return found


# ---------------------------------------------------------------------------
# Test 1: certificates
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/code-does-not-decide.md: record_management_certificates.py must supply the generated root "
    "hash and observed leaf SAN, observe read completeness, read warning_days from pack facts with date validity, "
    "and record derived findings instead of raising in Python.",
)
def test_certificates_recorder_lets_pack_decide_from_observed_tls_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Certificates recorder feeds generated root + real leaf SAN + pack warning_days and reads findings via batch.read."""
    source_path = CLUSTER_DIR / "record_management_certificates.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    # 1. Pack parameter fact supplies TLS warning_days; recorder holds no hardcoded warning_days, complete=True,
    #    or hardcoded days_valid day-offset integer constants.
    fact_rows = _platform_fact_rows()
    tls_warning_values = [
        row["warning_days"]
        for kind, rows in fact_rows.items()
        if any(tok in kind.lower() for tok in ("tls", "cert"))
        for row in rows
        if type(row.get("warning_days")) is int
    ]
    assert tls_warning_values, (
        "examples/platform/facts/ must declare a TLS parameter fact with warning_days so "
        "record_management_certificates.py does not hardcode warning_days in Python"
    )
    pack_warning_days = tls_warning_values[0]
    assert not _dict_literal_int_values(tree, "warning_days"), (
        "record_management_certificates.py still hardcodes warning_days as a Python integer literal"
    )
    assert not _dict_literal_bool_values(tree, "complete"), (
        "record_management_certificates.py still hardcodes tls_read complete=True instead of observing completeness"
    )
    hardcoded_days_valid = [
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "days_valid" and isinstance(kw.value, ast.Constant) and type(kw.value.value) is int
    ]
    assert not hardcoded_days_valid, (
        "record_management_certificates.py still passes hardcoded integer days_valid offsets "
        f"{hardcoded_days_valid!r} instead of expressing certificate validity as calendar dates"
    )

    # 2. Behavioral runs checked through rezono_compiler.batch.read and recorded renewal-judgement events.
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID

    cert_relations = (
        "tls_root__authority",
        "tls_leaf__dns_name",
        "tls_clock__warning_days",
        "tls_read__complete",
        "managed_tls_finding",
        "managed_tls_unknown",
    )

    def _run_cert_scenario(
        mode: str,
    ) -> tuple[set[tuple[str, str]], list[dict[str, set[tuple[str, ...]]]], list[dict[str, Any]], str]:
        seen, snapshots = _capture_batch_reads(monkeypatch, extra_relations=cert_relations)
        holder: dict[str, Any] = {"root_sha256": "", "leaf_obs": {}, "secret_rv": 0}

        class FakeCertCluster(_BaseFakeCluster):
            def __init__(self, env: dict[str, str] | None = None) -> None:
                super().__init__(tmp_path / f"cert-{mode}")
                holder["cluster"] = self

            def apply(self, manifest: dict[str, Any], limit: int = 30) -> None:
                super().apply(manifest, limit=limit)
                kind = manifest.get("kind")
                if kind == "ConfigMap" and "ca.crt" in (manifest.get("data") or {}):
                    pem = manifest["data"]["ca.crt"].encode("ascii")
                    root_cert = x509.load_pem_x509_certificate(pem)
                    holder["root_sha256"] = hashlib.sha256(
                        root_cert.public_bytes(serialization.Encoding.DER)
                    ).hexdigest()
                elif kind == "Secret" and "tls.crt" in (manifest.get("data") or {}):
                    holder["secret_rv"] += 1
                    chain_pem = base64.b64decode(manifest["data"]["tls.crt"])
                    certs = x509.load_pem_x509_certificates(chain_pem)
                    leaf, issuer = certs[0], certs[1]
                    sans = leaf.extensions.get_extension_for_class(
                        x509.SubjectAlternativeName
                    ).value.get_values_for_type(x509.DNSName)
                    holder["leaf_obs"][holder["secret_rv"]] = {
                        "verified_chain": True,
                        "verified_dns_name": sans[0] if sans else "",
                        "dns_names": list(sans),
                        "san_dns_names": list(sans),
                        "dns_name": sans[0] if sans else "",
                        "leaf_dns_name": sans[0] if sans else "",
                        "leaf_sha256": hashlib.sha256(leaf.public_bytes(serialization.Encoding.DER)).hexdigest(),
                        "issuer_sha256": hashlib.sha256(issuer.public_bytes(serialization.Encoding.DER)).hexdigest(),
                        "issuer_root_sha256": holder["root_sha256"],
                        "begins": leaf.not_valid_before_utc.strftime("%Y-%m-%d"),
                        "ends": leaf.not_valid_after_utc.strftime("%Y-%m-%d"),
                        "subject_cn": leaf.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                        "issuer_cn": issuer.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                        "serial_hex": format(leaf.serial_number, "x"),
                        "complete": True,
                        "banner": "ok\n",
                    }

            def read(self, *args: str, namespace: str | None = None, limit: int = 30) -> dict[str, Any]:
                super().read(*args, namespace=namespace, limit=limit)
                if len(args) >= 3 and args[0] == "get" and args[1] == "pod":
                    pod_name = args[2]
                    if mode == "incomplete" and "after" in pod_name:
                        return {"status": {"phase": "Failed"}}
                    return {"status": {"phase": "Succeeded"}}
                return {}

        def fake_run(*args: str, data: str | None = None, limit: int = 30, env: dict[str, str] | None = None) -> str:
            if "jsonpath={.metadata.resourceVersion}" in args:
                return str(holder["secret_rv"])
            if "rollout" in args:
                return "successfully rolled out\n"
            if "logs" in args:
                pod_name = args[args.index("logs") + 1]
                if "before" in pod_name:
                    return json.dumps(holder["leaf_obs"][1])
                if mode == "incomplete":
                    return json.dumps({"complete": False, "error": "dial tcp: connection refused"})
                if mode == "mismatch":
                    base_obs = dict(holder["leaf_obs"][2])
                    base_obs.update({
                        "verified_chain": False,
                        "verified_dns_name": "",
                        "dns_names": ["wrong.example.org"],
                        "san_dns_names": ["wrong.example.org"],
                        "dns_name": "wrong.example.org",
                        "leaf_dns_name": "wrong.example.org",
                        "presented_dns_name": "wrong.example.org",
                        "issuer_root_sha256": "f" * 64,
                        "issuer_sha256": "e" * 64,
                        "complete": True,
                    })
                    return json.dumps(base_obs)
                return json.dumps(holder["leaf_obs"][2])
            return ""

        mod = _load_recorder(
            monkeypatch,
            "record_management_certificates.py",
            fake_cluster_cls=FakeCertCluster,
            fake_run=fake_run,
        )
        try:
            mod.record_certificates()
        except RuntimeError as exc:
            raise AssertionError(
                f"record_management_certificates.py raised RuntimeError during {mode!r} instead of "
                f"recording derived findings/unknowns: {exc}"
            ) from exc
        cluster = holder["cluster"]
        assert cluster.recorded_jobs, f"record_management_certificates.py did not call record_job in {mode!r} mode"
        return seen, snapshots, cluster.recorded_jobs[-1][1], holder["root_sha256"]

    # Scenario A: untrusted root + wrong leaf SAN must derive untrusted-chain & wrong-name rows via batch.read.
    seen_a, snaps_a, events_a, generated_root = _run_cert_scenario("mismatch")
    assert {(PLATFORM_PACK_NAME, "managed_tls_finding"), (PLATFORM_PACK_NAME, "managed_tls_unknown")} <= seen_a, sorted(seen_a)
    rows_a = snaps_a[-1]
    assert {row[1] for row in rows_a["tls_root__authority"]} == {generated_root}, (
        "tls_root__authority must hold the generated trusted root hash, not echo the peer's observed root; "
        f"got {rows_a['tls_root__authority']!r}"
    )
    assert any(row[1] == "wrong.example.org" for row in rows_a["tls_leaf__dns_name"]), (
        f"tls_leaf__dns_name must hold the observed leaf SAN DNS name, got {rows_a['tls_leaf__dns_name']!r}"
    )
    assert {row[1] for row in rows_a["tls_clock__warning_days"]} == {str(pack_warning_days)}, (
        f"tls_clock__warning_days must match pack fact {pack_warning_days}; got {rows_a['tls_clock__warning_days']!r}"
    )
    assert {("renewed", "untrusted-chain"), ("renewed", "wrong-name")} <= rows_a["managed_tls_finding"], (
        f"Expected untrusted-chain and wrong-name in managed_tls_finding; got {rows_a['managed_tls_finding']!r}"
    )
    assert rows_a["managed_tls_unknown"] == set(), rows_a["managed_tls_unknown"]
    judgement_a, = [e for e in events_a if e["kind"] == "renewal-judgement"]
    recorded_findings_a = {tuple(row) for row in judgement_a.get("findings", [])}
    assert {("renewed", "untrusted-chain"), ("renewed", "wrong-name")} <= recorded_findings_a, (
        f"renewal-judgement must record derived finding rows; got {judgement_a!r}"
    )

    # Scenario B: incomplete read must record tls_read__complete=false and derive managed_tls_unknown={('renewed',)}.
    seen_b, snaps_b, events_b, _ = _run_cert_scenario("incomplete")
    assert (PLATFORM_PACK_NAME, "managed_tls_unknown") in seen_b, sorted(seen_b)
    rows_b = snaps_b[-1]
    assert any(row[1] == "false" for row in rows_b["tls_read__complete"]), (
        f"tls_read__complete must observe false when the probe fails; got {rows_b['tls_read__complete']!r}"
    )
    assert rows_b["managed_tls_unknown"] == {("renewed",)}, (
        f"Expected managed_tls_unknown == {{('renewed',)}}; got {rows_b['managed_tls_unknown']!r}"
    )
    judgement_b, = [e for e in events_b if e["kind"] == "renewal-judgement"]
    assert {tuple(row) for row in judgement_b.get("unknowns", [])} == {("renewed",)}, (
        f"renewal-judgement must record derived unknown row ('renewed',); got {judgement_b!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: health
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/code-does-not-decide.md: record_management_health.py must submit raw observed http_status "
    "and let the platform pack rule classify healthy/unhealthy instead of classifying in Python.",
)
def test_health_recorder_records_http_status_and_lets_pack_classify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Health recorder supplies raw HTTP status rows and reads classified health rows via rezono_compiler.batch.read."""
    health_relations = (
        "health_probe__status",
        "health_probe__http_status",
        "managed_health",
        "managed_health_complete",
        "managed_health_finding",
        "managed_telemetry_firewall",
    )

    def _run_health(
        status_by_subject: dict[str, int],
    ) -> tuple[set[tuple[str, str]], list[dict[str, set[tuple[str, ...]]]], list[dict[str, Any]]]:
        seen, snapshots = _capture_batch_reads(monkeypatch, extra_relations=health_relations)
        pod_ips = {
            "well-service": "10.0.0.10",
            "bad-service": "10.0.0.11",
            "telemetry-metrics": "10.0.0.20",
            "telemetry-logs": "10.0.0.21",
            "telemetry-alerts": "10.0.0.22",
        }
        ip_to_subject = {ip: name for name, ip in pod_ips.items()}
        deliveries: dict[str, list[dict[str, Any]]] = {"metrics": [], "logs": [], "alerts": []}
        holder: dict[str, Any] = {}

        class FakeHealthCluster(_BaseFakeCluster):
            def __init__(self) -> None:
                super().__init__(tmp_path / "health")
                holder["cluster"] = self

            def read(self, *args: str, namespace: str | None = None, limit: int = 30) -> dict[str, Any]:
                super().read(*args, namespace=namespace, limit=limit)
                if len(args) >= 3 and args[0] == "get" and args[1] == "pod":
                    return {"status": {"podIP": pod_ips[args[2]]}}
                if len(args) >= 3 and args[0] == "get" and args[1] == "service":
                    return {"spec": {"clusterIP": "10.96.0.99"}}
                if len(args) >= 3 and args[0] == "get" and args[1] == "endpoints":
                    return {"subsets": []}
                return {}

        def fake_run(*args: str, data: str | None = None, limit: int = 30, env: dict[str, str] | None = None) -> str:
            if "probe-http" in args:
                url = args[args.index("probe-http") + 1]
                if "10.96.0.99" in url:
                    return json.dumps({
                        "url": url,
                        "reachable": False,
                        "error": "dial tcp 10.96.0.99:8080: connect: connection refused",
                        "event_time": 1_700_000_102,
                    })
                if url.endswith("/deliveries"):
                    host = url.split("://", 1)[1].split(":", 1)[0]
                    channel = ip_to_subject[host].removeprefix("telemetry-")
                    return json.dumps({
                        "url": url,
                        "reachable": True,
                        "status_code": 200,
                        "body": json.dumps(deliveries[channel]),
                        "event_time": 1_700_000_105,
                    })
                host = url.split("://", 1)[1].split(":", 1)[0]
                subject = ip_to_subject[host]
                token = url.split("token=", 1)[1]
                code = status_by_subject[subject]
                return json.dumps({
                    "url": url,
                    "reachable": True,
                    "status_code": code,
                    "body": json.dumps({
                        "service": subject,
                        "token": token,
                        "status_code": code,
                        "event_time": 1_700_000_100,
                    }),
                    "event_time": 1_700_000_100,
                })
            if "post-json" in args:
                idx = args.index("post-json")
                url, payload = args[idx + 1], args[idx + 2]
                host_port = url.split("://", 1)[1].split("/", 1)[0]
                host, port_text = host_port.split(":", 1)
                channel = ip_to_subject[host].removeprefix("telemetry-")
                raw = payload.encode("utf-8")
                receipt = {
                    "channel": channel,
                    "port": int(port_text),
                    "received_at": 1_700_000_104,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "payload": payload,
                }
                deliveries[channel].append(receipt)
                return json.dumps(receipt)
            return ""

        mod = _load_recorder(
            monkeypatch,
            "record_management_health.py",
            fake_cluster_cls=FakeHealthCluster,
            fake_run=fake_run,
        )
        try:
            mod.main()
        except RuntimeError as exc:
            raise AssertionError(f"record_management_health.py raised unexpectedly: {exc}") from exc
        cluster = holder["cluster"]
        assert cluster.recorded_jobs, "record_management_health.py did not call record_job"
        return seen, snapshots, cluster.recorded_jobs[-1][1]

    # Scenario A: 200 for well-service, 503 for bad-service.
    seen_a, snaps_a, events_a = _run_health({"well-service": 200, "bad-service": 503})
    assert {
        (PLATFORM_PACK_NAME, "managed_health"),
        (PLATFORM_PACK_NAME, "managed_health_complete"),
        (PLATFORM_PACK_NAME, "managed_health_finding"),
        (PLATFORM_PACK_NAME, "managed_telemetry_firewall"),
    } <= seen_a, sorted(seen_a)
    rows_a = snaps_a[-1]
    assert rows_a.get("health_probe__status", set()) == set(), (
        "record_management_health.py must not pre-populate health_probe__status with Python-classified "
        f"'healthy'/'unhealthy' rows; got {rows_a.get('health_probe__status')!r}"
    )
    http_status_rows = rows_a.get("health_probe__http_status", set())
    assert {row[1] for row in http_status_rows} == {"200", "503"}, (
        "record_management_health.py must supply observed http_status rows {'200', '503'} in "
        f"health_probe__http_status for the pack rule to classify; got {http_status_rows!r}"
    )
    assert {(subject, state) for subject, state, _ in rows_a["managed_health"]} == {
        ("well-service", "healthy"),
        ("bad-service", "unhealthy"),
        ("unreachable-cluster", "unknown"),
    }, rows_a["managed_health"]
    assert {subject for subject, _ in rows_a["managed_health_complete"]} == {"well-service"}
    assert {subject for subject, _ in rows_a["managed_health_finding"]} == {"bad-service"}
    assert {e["subject"]: e["state"] for e in events_a if e["kind"] == "health"} == {
        "well-service": "healthy",
        "bad-service": "unhealthy",
        "unreachable-cluster": "unknown",
    }

    # Scenario B: swap 200/503 to verify pack rules classify the inverted observed HTTP status codes.
    _, snaps_b, events_b = _run_health({"well-service": 503, "bad-service": 200})
    rows_b = snaps_b[-1]
    assert {(subject, state) for subject, state, _ in rows_b["managed_health"]} == {
        ("well-service", "unhealthy"),
        ("bad-service", "healthy"),
        ("unreachable-cluster", "unknown"),
    }, rows_b["managed_health"]
    assert {subject for subject, _ in rows_b["managed_health_complete"]} == {"bad-service"}
    assert {subject for subject, _ in rows_b["managed_health_finding"]} == {"well-service"}
    assert {e["subject"]: e["state"] for e in events_b if e["kind"] == "health"} == {
        "well-service": "unhealthy",
        "bad-service": "healthy",
        "unreachable-cluster": "unknown",
    }

    # No Python-side 'healthy'/'unhealthy' classification string literals remain.
    source_path = CLUSTER_DIR / "record_management_health.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    string_literals = {
        node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not ({"healthy", "unhealthy"} & string_literals), (
        "record_management_health.py still contains Python 'healthy'/'unhealthy' classification literals"
    )


# ---------------------------------------------------------------------------
# Test 3: backup
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/code-does-not-decide.md: record_management_backup.py must use the stored object's real "
    "timestamp, read max_age_days/interval_days/retention_days from pack facts, observe active_authority, record "
    "outcomes as a judgement event, and evaluate through management_probes.compiled.",
)
def test_backup_recorder_uses_object_timestamp_pack_params_and_compiled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backup recorder reads policy days from pack facts, uses the object's real timestamp, and records derived rows."""
    source_path = CLUSTER_DIR / "record_management_backup.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    # 1. Policy parameters come strictly from platform pack facts (no day literals in code or test).
    fact_rows = _platform_fact_rows()
    pack_max_age = [
        row["max_age_days"]
        for rows in fact_rows.values()
        for row in rows
        if type(row.get("max_age_days")) is int
    ]
    pack_interval = [
        row["interval_days"]
        for rows in fact_rows.values()
        for row in rows
        if type(row.get("interval_days")) is int
    ]
    pack_retention = [
        row["retention_days"]
        for rows in fact_rows.values()
        for row in rows
        if type(row.get("retention_days")) is int
    ]
    assert pack_max_age and pack_interval and pack_retention, (
        "examples/platform/facts/ must supply backup policy facts for max_age_days, interval_days, and retention_days"
    )
    max_age_days = pack_max_age[0]
    interval_days = pack_interval[0]
    retention_days = pack_retention[0]

    for param in ("max_age_days", "interval_days", "retention_days"):
        assert not _dict_literal_int_values(tree, param), (
            f"record_management_backup.py still hardcodes {param!r} as an integer literal in Python"
        )
    for kw_node in _make_event_keyword_literals(tree, "active_authority"):
        assert not (isinstance(kw_node, ast.Constant) and type(kw_node.value) is bool), (
            "record_management_backup.py still hardcodes active_authority as a boolean literal instead of observing it"
        )

    # Derive the out-of-window object timestamp directly from the pack's max_age_days parameter.
    now_utc = datetime.now(timezone.utc)
    today = now_utc.strftime("%Y-%m-%d")
    old_dt = now_utc - timedelta(days=max_age_days + 1)
    old_day = old_dt.strftime("%Y-%m-%d")
    old_rfc3339 = old_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    backup_relations = (
        "backup_copy__taken",
        "backup_decision__max_age_days",
        "managed_backup_state",
        "managed_backup_restored",
        "managed_backup_route",
    )

    from rezono_compiler import facts as compiler_facts

    def _run_backup(
        *, observed_active_authority: bool
    ) -> tuple[
        set[tuple[str, str]],
        list[dict[str, set[tuple[str, ...]]]],
        list[dict[str, list[tuple[Any, ...]]]],
        list[Any],
        list[dict[str, Any]],
    ]:
        requested_names: list[Any] = []
        seen, snapshots = _capture_batch_reads(
            monkeypatch,
            extra_relations=backup_relations,
            on_read=lambda _pack, names, _snap: requested_names.append(names),
        )
        admitted_rows: list[dict[str, list[tuple[Any, ...]]]] = []
        real_rows_of = compiler_facts.rows_of

        def capture_rows_of(model: Any, records: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            tables = real_rows_of(model, records, *args, **kwargs)
            admitted_rows.append({name: list(vals) for name, vals in tables.items()})
            return tables

        monkeypatch.setattr(compiler_facts, "rows_of", capture_rows_of)
        state_box: dict[str, Any] = {"scaled": False, "stored": {}}

        class FakeBackupCluster(_BaseFakeCluster):
            def __init__(self) -> None:
                super().__init__(tmp_path / f"backup-{observed_active_authority}")
                state_box["cluster"] = self

            def read(self, *args: str, namespace: str | None = None, limit: int = 30) -> dict[str, Any]:
                super().read(*args, namespace=namespace, limit=limit)
                if len(args) >= 2 and args[0] == "get" and args[1] == "pods":
                    if "job-name=rezono-mgmt-restore" in args:
                        return {
                            "items": [{
                                "metadata": {
                                    "name": "rezono-mgmt-restore-pod",
                                    "ownerReferences": [{"uid": "restore-job-uid", "controller": True}],
                                },
                                "status": {"phase": "Succeeded"},
                            }]
                        }
                    if state_box["scaled"] and not observed_active_authority:
                        return {"items": []}
                    return {
                        "items": [{
                            "metadata": {"name": "rezono-mgmt-plane-0"},
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                        }]
                    }
                if len(args) >= 3 and args[0] == "get" and args[1] == "service":
                    return {"spec": {"clusterIP": "10.96.0.50"}}
                if len(args) >= 2 and args[0] == "get" and args[1] == "endpointslices":
                    return {"items": []}
                if len(args) >= 3 and args[0] == "get" and args[1] == "job":
                    return {"metadata": {"uid": "restore-job-uid"}}
                if len(args) >= 2 and args[0] == "get" and args[1] in {"deployment", "deployments"}:
                    ready = 1 if observed_active_authority else 0
                    return {"spec": {"replicas": ready}, "status": {"readyReplicas": ready, "availableReplicas": ready}}
                return {}

        def fake_run(*args: str, data: str | None = None, limit: int = 30, env: dict[str, str] | None = None) -> str:
            if "scale" in args:
                state_box["scaled"] = True
                return "deployment.apps/rezono-mgmt-plane scaled\n"
            if "probe" in args:
                if not state_box["scaled"]:
                    return json.dumps({"address": "10.96.0.50:8080", "reachable": True, "status": 200})
                return json.dumps({
                    "address": "10.96.0.50:8080",
                    "reachable": False,
                    "error": "dial tcp 10.96.0.50:8080: connect: connection refused",
                })
            if "put" in args:
                key = args[args.index("put") + 2]
                raw = (data or "").encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                record = {
                    "key": key,
                    "sha256": digest,
                    "size": len(raw),
                    "stored_at": old_rfc3339,
                    "created_at": old_rfc3339,
                    "last_modified": old_rfc3339,
                    "taken_at": old_rfc3339,
                    "timestamp": old_rfc3339,
                    "taken": old_day,
                }
                state_box["stored"][key] = record
                return json.dumps(record)
            if "logs" in args:
                stored = next(iter(state_box["stored"].values()))
                return json.dumps({
                    "key": stored["key"],
                    "sha256": stored["sha256"],
                    "size": stored["size"],
                    "stored_at": old_rfc3339,
                    "created_at": old_rfc3339,
                    "last_modified": old_rfc3339,
                    "taken_at": old_rfc3339,
                    "taken": old_day,
                    "mgmt_dial_error": "dial tcp 10.96.0.50:8080: connect: connection refused",
                    "isolated": True,
                    "active_authority": observed_active_authority,
                })
            return ""

        mod = _load_recorder(
            monkeypatch,
            "record_management_backup.py",
            fake_cluster_cls=FakeBackupCluster,
            fake_run=fake_run,
        )
        try:
            mod.main()
        except RuntimeError as exc:
            raise AssertionError(
                "record_management_backup.py raised RuntimeError instead of recording derived backup "
                f"judgement rows: {exc}"
            ) from exc
        cluster = state_box["cluster"]
        assert cluster.recorded_jobs, "record_management_backup.py did not call record_job"
        return seen, snapshots, admitted_rows, requested_names, cluster.recorded_jobs[-1][1]

    # Scenario A: stale stored object (max_age_days + 1 days old) derives too-old via management_probes.compiled.
    seen_a, snaps_a, admitted_a, req_names_a, events_a = _run_backup(observed_active_authority=False)
    assert {
        (PLATFORM_PACK_NAME, "managed_backup_state"),
        (PLATFORM_PACK_NAME, "managed_backup_restored"),
        (PLATFORM_PACK_NAME, "managed_backup_route"),
    } <= seen_a, sorted(seen_a)
    assert any(names is None for names in req_names_a), (
        "record_management_backup.py must evaluate the full platform pack via management_probes.compiled "
        "(reading all derived relations through batch.read(con, prog)), not a custom subset evaluator"
    )
    rows_a = snaps_a[-1]
    assert {row[1] for row in rows_a.get("backup_copy__taken", set())} == {old_day} and old_day != today, (
        f"backup_copy__taken must record the stored object's real date ({old_day}), not as_of ({today}); "
        f"got {rows_a.get('backup_copy__taken')!r}"
    )
    assert {row[1] for row in rows_a.get("backup_decision__max_age_days", set())} == {str(max_age_days)}, (
        f"backup_decision__max_age_days must match pack fact {max_age_days}; "
        f"got {rows_a.get('backup_decision__max_age_days')!r}"
    )
    assert admitted_a, "record_management_backup.py must admit input facts through rezono_compiler.facts.rows_of"
    fact_tables_a = admitted_a[-1]
    assert {str(row[1]) for row in fact_tables_a.get("backup_plan__interval_days", ())} == {str(interval_days)}, (
        f"backup_plan__interval_days must match pack fact {interval_days}; "
        f"got {fact_tables_a.get('backup_plan__interval_days')!r}"
    )
    assert {str(row[1]) for row in fact_tables_a.get("backup_plan__retention_days", ())} == {str(retention_days)}, (
        f"backup_plan__retention_days must match pack fact {retention_days}; "
        f"got {fact_tables_a.get('backup_plan__retention_days')!r}"
    )
    assert rows_a["managed_backup_state"] == {("management-backup-plan", "too-old")}, rows_a["managed_backup_state"]
    backup_id = "management-copy-404-1"
    trial_id = "management-trial-404-1"
    store_endpoint = "rezono-mgmt-backup-store.rezono-mgmt-store.svc.cluster.local:8080"
    assert rows_a["managed_backup_restored"] == {(backup_id, trial_id)}, rows_a["managed_backup_restored"]
    assert rows_a["managed_backup_route"] == {
        ("management", store_endpoint, "write"),
        ("recovery", store_endpoint, "read"),
    }, rows_a["managed_backup_route"]

    judgement_events = [
        e for e in events_a
        if e["kind"] not in {"backup-completed", "management-unreachable", "recovered-read"}
    ]
    assert judgement_events, (
        "record_management_backup.py must record the derived backup outcomes as a judgement event instead of "
        f"discarding them; recorded kinds={[e['kind'] for e in events_a]!r}"
    )
    recorded_rows = set().union(*(_event_row_tuples(e) for e in judgement_events))
    assert {
        ("management-backup-plan", "too-old"),
        (backup_id, trial_id),
        ("management", store_endpoint, "write"),
        ("recovery", store_endpoint, "read"),
    } <= recorded_rows, (
        f"Backup judgement event must record exact derived relation rows; got rows={sorted(recorded_rows)!r}"
    )

    # Scenario B: observing active_authority=True propagates into recovered-read (not hardcoded False).
    _, _, _, _, events_b = _run_backup(observed_active_authority=True)
    recovered_active, = [e for e in events_b if e["kind"] == "recovered-read"]
    assert recovered_active.get("active_authority") is True, (
        f"recovered-read must record the observed active_authority value, got {recovered_active!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: access
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M2: decisions/code-does-not-decide.md: record_management_access.py must render the K8s Role from "
    "derived managed_cluster_right, contain no hardcoded calendar dates, compute weight=-1 via the publication "
    "difference path, and observe completeness over both Roles and RoleBindings.",
)
def test_access_recorder_renders_role_from_derived_right_and_publication_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Access recorder renders Role from managed_cluster_right, diffs publications for weight=-1, and reads Roles too."""
    from rezono_compiler import facts as compiler_facts
    import rezono_publisher.difference as pub_diff

    source_path = CLUSTER_DIR / "record_management_access.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    identity = "system:serviceaccount:elm:reader"
    access_relations = ("managed_cluster_right", "cluster_right_clock__day")

    def _run_access(
        *,
        override_action_resource: tuple[str, str] | None = None,
        roles_remaining_item_count: int | None = None,
        keep_membership_active: bool = False,
    ) -> tuple[
        _BaseFakeCluster,
        set[tuple[str, str]],
        list[dict[str, set[tuple[str, ...]]]],
        list[dict[str, Any]],
    ]:
        monkeypatch.delenv("GITHUB_ENV", raising=False)
        seen, snapshots = _capture_batch_reads(monkeypatch, extra_relations=access_relations)

        orig_rows_of = compiler_facts.rows_of
        clock_days_seen: list[str] = []

        def adjust_inputs(model: Any, records: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            updated = dict(records)
            if override_action_resource is not None and "cluster_action_decision" in updated:
                action, resource = override_action_resource
                updated["cluster_action_decision"] = [
                    (
                        {**row, "action": action, "resource": resource}
                        if row.get("organization") == "elm"
                        else dict(row)
                    )
                    for row in updated["cluster_action_decision"]
                ]
            if keep_membership_active and "cluster_right_clock" in updated and updated["cluster_right_clock"]:
                day = updated["cluster_right_clock"][0]["day"]
                if not clock_days_seen:
                    clock_days_seen.append(day)
                else:
                    updated["cluster_right_clock"] = [
                        {**updated["cluster_right_clock"][0], "day": clock_days_seen[0]}
                    ]
            return orig_rows_of(model, updated, *args, **kwargs)

        monkeypatch.setattr(compiler_facts, "rows_of", adjust_inputs)

        holder: dict[str, Any] = {"binding_applied": False, "last_binding": None}

        class FakeAccessCluster(_BaseFakeCluster):
            def __init__(self, env: dict[str, str] | None = None) -> None:
                super().__init__(
                    tmp_path / f"access-{override_action_resource}-{roles_remaining_item_count}-{keep_membership_active}"
                )
                holder["cluster"] = self

            def apply(self, manifest: dict[str, Any], limit: int = 30) -> None:
                super().apply(manifest, limit=limit)
                if manifest.get("kind") == "RoleBinding":
                    holder["binding_applied"] = True
                    holder["last_binding"] = manifest

            def delete(self, *args: str, namespace: str | None = None, limit: int = 45) -> None:
                super().delete(*args, namespace=namespace, limit=limit)
                if any("role" in arg for arg in args):
                    holder["binding_applied"] = False

            def read(self, *args: str, namespace: str | None = None, limit: int = 30) -> dict[str, Any]:
                super().read(*args, namespace=namespace, limit=limit)
                if len(args) >= 2 and args[0] == "get":
                    target = args[1]
                    if target == "rolebinding" and holder["last_binding"] is not None:
                        meta = dict(holder["last_binding"].get("metadata", {}))
                        meta["uid"] = "fake-binding-uid-1"
                        return {**holder["last_binding"], "metadata": meta}
                    if target in {"rolebindings", "rolebinding"}:
                        return {"items": [], "metadata": {}}
                    if target in {"roles", "role"}:
                        meta: dict[str, Any] = {}
                        if roles_remaining_item_count is not None:
                            meta["remainingItemCount"] = roles_remaining_item_count
                        return {"items": [], "metadata": meta}
                return {}

        ca_b64 = base64.b64encode(b"FAKE-CA-PEM").decode("ascii")

        def fake_run(*args: str, data: str | None = None, limit: int = 30, env: dict[str, str] | None = None) -> str:
            if "config" in args and "view" in args:
                return json.dumps({
                    "clusters": [{
                        "cluster": {
                            "server": "https://127.0.0.1:6443",
                            "certificate-authority-data": ca_b64,
                        }
                    }]
                })
            if "create" in args and "--raw" in args:
                return json.dumps({
                    "status": {
                        "token": "fake-tenant-token",
                        "expirationTimestamp": "2099-01-01T00:00:00Z",
                    }
                })
            if "whoami" in args:
                return json.dumps({"status": {"userInfo": {"username": identity}}})
            return ""

        class _FakeResponse:
            def __init__(self, body: bytes, status: int = 200, reason: str = "OK") -> None:
                self._body = body
                self.status = status
                self.reason = reason

            def read(self) -> bytes:
                return self._body

            def __enter__(self) -> _FakeResponse:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        def fake_urlopen(request: urllib.request.Request, context: Any = None, timeout: int = 15) -> _FakeResponse:
            url = request.full_url
            if "/namespaces/elm/" in url and holder["binding_applied"]:
                payload = json.dumps({"kind": "ConfigMap", "metadata": {"name": "public-marker"}}).encode("utf-8")
                return _FakeResponse(payload, status=200, reason="OK")
            raise urllib.error.HTTPError(
                url,
                403,
                "Forbidden",
                hdrs=None,  # type: ignore[arg-type]
                fp=io.BytesIO(b'{"reason":"Forbidden"}'),
            )

        monkeypatch.setattr(ssl, "create_default_context", lambda *args, **kwargs: object())
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        mod = _load_recorder(
            monkeypatch,
            "record_management_access.py",
            fake_cluster_cls=FakeAccessCluster,
            fake_run=fake_run,
        )
        try:
            mod.main()
        except RuntimeError as exc:
            raise AssertionError(
                "record_management_access.py raised RuntimeError instead of rendering from derived "
                f"managed_cluster_right and diffing publications: {exc}"
            ) from exc
        cluster = holder["cluster"]
        assert cluster.recorded_jobs, "record_management_access.py did not call record_job"
        return cluster, seen, snapshots, cluster.recorded_jobs[-1][1]

    # Scenario A: before/after managed_cluster_right rows via batch.read + both Roles and RoleBindings read.
    cluster_a, seen_a, snaps_a, events_a = _run_access()
    assert (PLATFORM_PACK_NAME, "managed_cluster_right") in seen_a, sorted(seen_a)
    rights_history = [s["managed_cluster_right"] for s in snaps_a if "managed_cluster_right" in s]
    elm_right = (identity, "elm-app", "get", "configmaps", "elm")
    reed_right = ("peer", "reed-app", "get", "configmaps", "reed")
    assert rights_history[0] == {elm_right, reed_right}, rights_history[0]
    assert rights_history[-1] == {reed_right}, rights_history[-1]
    before_json = json.dumps([{"key": list(row)} for row in sorted(rights_history[0])]).encode("utf-8")
    after_json = json.dumps([{"key": list(row)} for row in sorted(rights_history[-1])]).encode("utf-8")
    assert pub_diff.entries(before_json, after_json) == [{"key": list(elm_right), "change": "removed"}]

    read_targets = {args[1] for args, _ in cluster_a.reads if len(args) >= 2 and args[0] == "get"}
    assert ("rolebindings" in read_targets or "rolebinding" in read_targets) and (
        "roles" in read_targets or "role" in read_targets
    ), f"Absence confirmation must read both RoleBindings and Roles; saw cluster.read targets={sorted(read_targets)!r}"
    withdrawn_a, = [e for e in events_a if e["kind"] == "right-withdrawn"]
    assert withdrawn_a["weight"] == -1

    # Scenario B: changing derived managed_cluster_right changes the rendered K8s Role manifest.
    cluster_b, _, snaps_b, _ = _run_access(override_action_resource=("list", "services"))
    assert (identity, "elm-app", "list", "services", "elm") in snaps_b[0]["managed_cluster_right"]
    applied_roles = [m for m in cluster_b.applied if m.get("kind") == "Role"]
    assert applied_roles, "Expected a K8s Role manifest to be applied"
    role_rules = applied_roles[-1].get("rules", [])
    rendered_verbs = {v for rule in role_rules for v in rule.get("verbs", [])}
    rendered_resources = {r for rule in role_rules for r in rule.get("resources", [])}
    assert rendered_verbs == {"list"} and rendered_resources == {"services"}, (
        "K8s Role must be rendered from the derived managed_cluster_right row (verbs={'list'}, "
        f"resources={{'services'}}), not from a second hand-written copy; got rules={role_rules!r}"
    )

    # Scenario C: incomplete Roles pagination (remainingItemCount=1) makes binding-read-absent.complete False.
    _, _, _, events_c = _run_access(roles_remaining_item_count=1)
    absent_c, = [e for e in events_c if e["kind"] == "binding-read-absent"]
    assert absent_c.get("complete") is False, (
        "binding-read-absent.complete must observe completeness over Roles as well as RoleBindings "
        f"(expected False when Roles listing has remainingItemCount=1); got {absent_c!r}"
    )

    # Scenario D: when before and after managed_cluster_right snapshots are identical, the publication diff is empty
    # and no right-withdrawn (weight=-1) event may be emitted.
    _, _, _, events_d = _run_access(keep_membership_active=True)
    assert [e for e in events_d if e["kind"] == "right-withdrawn"] == [], (
        "When before and after managed_cluster_right snapshots have no publication difference, "
        "record_management_access.py must not fabricate a right-withdrawn (weight=-1) event"
    )

    # Structural guards: no hardcoded calendar dates and no hardcoded literal weight=-1 in make_event.
    hardcoded_dates = sorted({
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and ISO_DATE_RE.match(node.value)
    })
    assert not hardcoded_dates, (
        f"record_management_access.py still contains hardcoded calendar date literals: {hardcoded_dates}"
    )
    for kw_node in _make_event_keyword_literals(tree, "weight"):
        assert not _is_int_literal(kw_node, -1), (
            "record_management_access.py still hardcodes weight=-1 directly in make_event instead of deriving "
            "it from the publication diff path"
        )


# ---------------------------------------------------------------------------
# Test 5: firewall
# ---------------------------------------------------------------------------


def test_firewall_recorder_derives_allowances_and_witnessed_read_completeness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Firewall recorder derives allowances via batch.read before apply and relies on witnessed read completeness."""
    _ensure_paths(monkeypatch)
    import router_render

    source_path = CLUSTER_DIR / "record_management_firewall.py"
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))

    firewall_relations = (
        "managed_router_drift",
        "managed_router_unknown",
        "complete_router_sweep",
        "may_read_full",
    )

    def _nft_rule_json(handle: int, port: int) -> dict[str, Any]:
        return {
            "rule": {
                "family": "ip",
                "table": "rezono_fixture",
                "chain": "forward",
                "handle": handle,
                "expr": [
                    {
                        "match": {
                            "op": "==",
                            "left": {"payload": {"protocol": "ip", "field": "saddr"}},
                            "right": {"range": ["192.0.2.0", "192.0.2.15"]},
                        }
                    },
                    {
                        "match": {
                            "op": "==",
                            "left": {"payload": {"protocol": "ip", "field": "daddr"}},
                            "right": "198.51.100.7",
                        }
                    },
                    {
                        "match": {
                            "op": "==",
                            "left": {"payload": {"protocol": "tcp", "field": "dport"}},
                            "right": port,
                        }
                    },
                    {"accept": None},
                ],
            }
        }

    def _run_firewall(
        *, omit_chain_on_final_read: bool
    ) -> tuple[set[tuple[str, str]], list[dict[str, set[tuple[str, ...]]]], list[dict[str, Any]], list[str]]:
        timeline: list[str] = []
        seen, snapshots = _capture_batch_reads(
            monkeypatch,
            extra_relations=firewall_relations,
            on_read=lambda pack_name, _names, _snap: timeline.append(f"batch.read:{pack_name}"),
        )
        holder: dict[str, Any] = {"list_calls": 0, "rules": [(10, 443), (11, 8443)]}

        class FakeFirewallCluster(_BaseFakeCluster):
            def __init__(self) -> None:
                super().__init__(tmp_path / f"fw-{omit_chain_on_final_read}")
                holder["cluster"] = self

        def fake_sudo(*args: str, data: str | None = None) -> str:
            if "nft" in args and "-f" in args:
                timeline.append("nft-apply")
                return ""
            if "nft" in args and "list" in args:
                holder["list_calls"] += 1
                items: list[dict[str, Any]] = [
                    {"table": {"family": "ip", "name": "rezono_fixture"}},
                ]
                include_chain = not (omit_chain_on_final_read and holder["list_calls"] >= 2)
                if include_chain:
                    items.append({
                        "chain": {
                            "family": "ip",
                            "table": "rezono_fixture",
                            "name": "forward",
                            "type": "filter",
                            "hook": "forward",
                            "policy": "drop",
                        }
                    })
                for handle, port in holder["rules"]:
                    items.append(_nft_rule_json(handle, port))
                return json.dumps({"nftables": items})
            if "nft" in args and "delete" in args and "handle" in args:
                handle = int(args[args.index("handle") + 1])
                holder["rules"] = [pair for pair in holder["rules"] if pair[0] != handle]
            if "nft" in args and "add" in args and "dport" in args:
                port = int(args[args.index("dport") + 1])
                holder["rules"].append((12, port))
            return ""

        mod = _load_recorder(
            monkeypatch,
            "record_management_firewall.py",
            fake_cluster_cls=FakeFirewallCluster,
            fake_sudo=fake_sudo,
        )
        try:
            mod.main()
        except RuntimeError as exc:
            raise AssertionError(
                f"record_management_firewall.py raised RuntimeError (omit_chain={omit_chain_on_final_read}) "
                f"instead of submitting observed read scope and letting pack completeness decide: {exc}"
            ) from exc
        cluster = holder["cluster"]
        assert cluster.recorded_jobs, "record_management_firewall.py did not call record_job"
        return seen, snapshots, cluster.recorded_jobs[-1][1], timeline

    # Scenario A: complete readback — desired allowances must be read from platform via batch.read BEFORE nft apply.
    seen_a, snaps_a, events_a, timeline_a = _run_firewall(omit_chain_on_final_read=False)
    pack_read_marker = f"batch.read:{PLATFORM_PACK_NAME}"
    assert "nft-apply" in timeline_a and pack_read_marker in timeline_a, timeline_a
    assert timeline_a.index(pack_read_marker) < timeline_a.index("nft-apply"), (
        "Desired router allowances must be derived from the platform pack via batch.read BEFORE applying "
        f"rendered nftables bytes; saw timeline={timeline_a!r}"
    )
    assert {(PLATFORM_PACK_NAME, "managed_router_drift"), (PLATFORM_PACK_NAME, "managed_router_unknown")} <= seen_a, sorted(seen_a)
    rows_a = snaps_a[-1]
    assert any(kind == "router_seen" for _, kind in rows_a.get("may_read_full", set())), (
        "Platform firewall rules must derive witnessed read completeness row may_read_full(_, 'router_seen') "
        f"via batch.read; got may_read_full={rows_a.get('may_read_full', set())!r}"
    )
    assert rows_a["managed_router_unknown"] == set(), rows_a["managed_router_unknown"]
    assert {direction for direction, _, _ in rows_a["managed_router_drift"]} == {"missing", "extra"}
    assert len(rows_a["managed_router_drift"]) == 2

    desired_event, = [e for e in events_a if e["kind"] == "desired-router-publication"]
    assert hashlib.sha256(router_render.render(desired_event["rules"])).hexdigest() == desired_event["applied_sha256"]
    read_complete, = [e for e in events_a if e["kind"] == "complete-router-read"]
    assert read_complete["complete"] is True
    drift_complete = [e for e in events_a if e["kind"] == "router-drift"]
    assert {e["direction"] for e in drift_complete} == {"missing", "extra"}

    # Scenario B: incomplete nft readback (missing forward chain) must NOT raise in Python;
    # batch.read must derive managed_router_unknown={('404', 'boundary', 'rezono_fixture')} and empty drift.
    _, snaps_b, events_b, _ = _run_firewall(omit_chain_on_final_read=True)
    rows_b = snaps_b[-1]
    assert rows_b["managed_router_unknown"] == {("404", "boundary", "rezono_fixture")}, (
        f"Incomplete readback must derive managed_router_unknown; got {rows_b['managed_router_unknown']!r}"
    )
    assert rows_b["managed_router_drift"] == set(), (
        f"Incomplete readback must not derive managed_router_drift; got {rows_b['managed_router_drift']!r}"
    )
    read_events_b = [e for e in events_b if "read" in e["kind"]]
    assert read_events_b, f"Expected a recorded router read event on incomplete readback; got {events_b!r}"
    assert read_events_b[-1].get("complete") is False, (
        "Incomplete nftables readback (missing forward chain) must record complete=False from read-scope rules, "
        f"not hardcoded complete=True; got {read_events_b[-1]!r}"
    )
    assert [e for e in events_b if e["kind"] == "router-drift"] == [], (
        "Incomplete router readback must not emit router-drift events"
    )

    # Structural guard: no hardcoded complete=True in make_event.
    for kw_node in _make_event_keyword_literals(tree, "complete"):
        assert not (isinstance(kw_node, ast.Constant) and kw_node.value is True), (
            "record_management_firewall.py still hardcodes complete=True in make_event"
        )
