"""Record real TLS issuance, handshake, renewal, and evaluation on the disposable cluster."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from management_recorder import ManagementCluster, ROOT, run

for _extra in (ROOT / "examples", ROOT / "examples" / "platform" / "proof_cases"):
    _text = str(_extra)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from management_probes import _committed, compiled  # noqa: E402
from rezono_compiler import facts  # noqa: E402

FEATURE = "certificates"
PLATFORM_PACK = ROOT / "examples" / "platform"
TLS_IMAGE = "docker.io/library/rezono-tls-fixture:local"
EXPECTED_NAME = "renewed.example.org"
CALLER = "client"
SERVICE_NAME = "renewed-tls"
SECRET_NAME = "renewed-tls-secret"
CA_CONFIGMAP_NAME = "tls-trust-root"
TLS_PORT = 8443
SERVICE_PORT = 443

GO_SOURCE = """\
// Minimal TLS server and ordinary verifying client probe for the disposable cluster fixture.
package main

import (
\t"bufio"
\t"crypto/sha256"
\t"crypto/tls"
\t"crypto/x509"
\t"encoding/hex"
\t"encoding/json"
\t"fmt"
\t"io"
\t"net"
\t"os"
\t"time"
)

type observation struct {
\tVerifiedChain    bool   `json:"verified_chain"`
\tVerifiedDNSName  string `json:"verified_dns_name"`
\tLeafSHA256       string `json:"leaf_sha256"`
\tIssuerSHA256     string `json:"issuer_sha256"`
\tIssuerRootSHA256 string `json:"issuer_root_sha256"`
\tBegins           string `json:"begins"`
\tEnds             string `json:"ends"`
\tSubjectCN        string `json:"subject_cn"`
\tIssuerCN         string `json:"issuer_cn"`
\tSerialHex        string `json:"serial_hex"`
\tBanner           string `json:"banner"`
}

func sha256Hex(raw []byte) string {
\tsum := sha256.Sum256(raw)
\treturn hex.EncodeToString(sum[:])
}

func serve(args []string) error {
\tif len(args) != 3 {
\t\treturn fmt.Errorf("expected <addr> <cert-file> <key-file>")
\t}
\taddr, certFile, keyFile := args[0], args[1], args[2]
\tif _, err := tls.LoadX509KeyPair(certFile, keyFile); err != nil {
\t\treturn err
\t}
\tcfg := &tls.Config{
\t\tMinVersion: tls.VersionTLS12,
\t\tGetCertificate: func(*tls.ClientHelloInfo) (*tls.Certificate, error) {
\t\t\tcert, err := tls.LoadX509KeyPair(certFile, keyFile)
\t\t\tif err != nil {
\t\t\t\treturn nil, err
\t\t\t}
\t\t\treturn &cert, nil
\t\t},
\t}
\tln, err := tls.Listen("tcp4", addr, cfg)
\tif err != nil {
\t\treturn err
\t}
\tdefer ln.Close()
\tfor {
\t\tconn, err := ln.Accept()
\t\tif err != nil {
\t\t\treturn err
\t\t}
\t\tgo func(c net.Conn) {
\t\t\tdefer c.Close()
\t\t\t_ = c.SetDeadline(time.Now().Add(10 * time.Second))
\t\t\ttlsConn, ok := c.(*tls.Conn)
\t\t\tif !ok {
\t\t\t\treturn
\t\t\t}
\t\t\tif err := tlsConn.Handshake(); err != nil {
\t\t\t\treturn
\t\t\t}
\t\t\t_, _ = io.WriteString(tlsConn, "ok\\n")
\t\t}(conn)
\t}
}

func probe(args []string) error {
\tif len(args) != 3 {
\t\treturn fmt.Errorf("expected <addr> <server-name> <ca-file>")
\t}
\taddr, serverName, caFile := args[0], args[1], args[2]
\tcaPEM, err := os.ReadFile(caFile)
\tif err != nil {
\t\treturn err
\t}
\troots := x509.NewCertPool()
\tif !roots.AppendCertsFromPEM(caPEM) {
\t\treturn fmt.Errorf("failed to parse root CA certificates")
\t}
\tcfg := &tls.Config{
\t\tMinVersion: tls.VersionTLS12,
\t\tServerName: serverName,
\t\tRootCAs:    roots,
\t}
\tdialer := &net.Dialer{Timeout: 10 * time.Second}
\tvar conn *tls.Conn
\tvar lastErr error
\tfor attempt := 0; attempt < 20; attempt++ {
\t\tconn, lastErr = tls.DialWithDialer(dialer, "tcp4", addr, cfg)
\t\tif lastErr == nil {
\t\t\tbreak
\t\t}
\t\ttime.Sleep(1 * time.Second)
\t}
\tif lastErr != nil {
\t\treturn lastErr
\t}
\tdefer conn.Close()
\t_ = conn.SetDeadline(time.Now().Add(10 * time.Second))
\tbanner, err := bufio.NewReader(conn).ReadString('\\n')
\tif err != nil {
\t\treturn err
\t}
\tstate := conn.ConnectionState()
\tif len(state.VerifiedChains) == 0 || len(state.VerifiedChains[0]) < 2 {
\t\treturn fmt.Errorf("expected verified certificate chain with root anchor")
\t}
\tchain := state.VerifiedChains[0]
\tleaf := chain[0]
\tissuer := chain[1]
\troot := chain[len(chain)-1]
\tif err := leaf.VerifyHostname(serverName); err != nil {
\t\treturn err
\t}
\tout := observation{
\t\tVerifiedChain:    true,
\t\tVerifiedDNSName:  serverName,
\t\tLeafSHA256:       sha256Hex(leaf.Raw),
\t\tIssuerSHA256:     sha256Hex(issuer.Raw),
\t\tIssuerRootSHA256: sha256Hex(root.Raw),
\t\tBegins:           leaf.NotBefore.UTC().Format("2006-01-02"),
\t\tEnds:             leaf.NotAfter.UTC().Format("2006-01-02"),
\t\tSubjectCN:        leaf.Subject.CommonName,
\t\tIssuerCN:         leaf.Issuer.CommonName,
\t\tSerialHex:        leaf.SerialNumber.Text(16),
\t\tBanner:           banner,
\t}
\treturn json.NewEncoder(os.Stdout).Encode(out)
}

func run(args []string) error {
\tif len(args) == 0 {
\t\treturn fmt.Errorf("expected serve or probe")
\t}
\tswitch args[0] {
\tcase "serve":
\t\treturn serve(args[1:])
\tcase "probe":
\t\treturn probe(args[1:])
\tdefault:
\t\treturn fmt.Errorf("unsupported command %q", args[0])
\t}
}

func main() {
\tif err := run(os.Args[1:]); err != nil {
\t\tfmt.Fprintln(os.Stderr, err)
\t\tos.Exit(1)
\t}
}
"""


def _cert_sha256(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _cert_pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _write_secret_file(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)


def _build_ca(
    common_name: str,
    not_valid_before: datetime,
    not_valid_after: datetime,
    path_length: int,
    issuer_cert: x509.Certificate | None = None,
    issuer_key: ec.EllipticCurvePrivateKey | None = None,
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Rezono"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    signing_key = key if issuer_key is None else issuer_key
    issuer_name = subject if issuer_cert is None else issuer_cert.subject
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    aki = (
        x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key())
        if issuer_cert is None
        else x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
            issuer_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
        )
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=path_length), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ski, critical=False)
        .add_extension(aki, critical=False)
        .sign(signing_key, hashes.SHA256())
    )
    return key, cert


def _build_leaf(
    dns_name: str,
    not_valid_before: datetime,
    not_valid_after: datetime,
    issuer_cert: x509.Certificate,
    issuer_key: ec.EllipticCurvePrivateKey,
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_name)])
    issuer_ski = issuer_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns_name)]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(issuer_ski), critical=False)
        .sign(issuer_key, hashes.SHA256())
    )
    return key, cert


def _build_tls_image(cluster: ManagementCluster, work_dir: Path) -> None:
    source_path = work_dir / "tls_fixture.go"
    source_path.write_text(GO_SOURCE, encoding="utf-8")
    cluster.build_go_image(source_path, TLS_IMAGE, "tls-fixture")


def _apply_tls_secret(
    cluster: ManagementCluster,
    namespace: str,
    leaf_cert: x509.Certificate,
    intermediate_cert: x509.Certificate,
    leaf_key: ec.EllipticCurvePrivateKey,
) -> str:
    chain_pem = _cert_pem(leaf_cert) + _cert_pem(intermediate_cert)
    key_pem = _key_pem(leaf_key)
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": SECRET_NAME, "namespace": namespace},
        "type": "kubernetes.io/tls",
        "data": {
            "tls.crt": base64.b64encode(chain_pem).decode("ascii"),
            "tls.key": base64.b64encode(key_pem).decode("ascii"),
        },
    })
    return run(
        *cluster.namespaced(namespace, "get", "secret", SECRET_NAME, "-o", "jsonpath={.metadata.resourceVersion}"),
        limit=25,
    ).strip()


def _deploy_tls_server(cluster: ManagementCluster, namespace: str) -> None:
    labels = {"app": SERVICE_NAME}
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": SERVICE_NAME, "namespace": namespace, "labels": labels},
        "spec": {
            "selector": labels,
            "ports": [{"name": "tls", "port": SERVICE_PORT, "targetPort": TLS_PORT, "protocol": "TCP"}],
        },
    })
    cluster.apply({
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": SERVICE_NAME, "namespace": namespace, "labels": labels},
        "spec": {
            "replicas": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": {"fsGroup": 65534},
                    "containers": [{
                        "name": "tls-server",
                        "image": TLS_IMAGE,
                        "imagePullPolicy": "Never",
                        "command": ["/tls-fixture", "serve", f":{TLS_PORT}", "/tls/tls.crt", "/tls/tls.key"],
                        "ports": [{"name": "tls", "containerPort": TLS_PORT, "protocol": "TCP"}],
                        "readinessProbe": {"tcpSocket": {"port": TLS_PORT}, "periodSeconds": 1},
                        "volumeMounts": [{"name": "tls", "mountPath": "/tls", "readOnly": True}],
                    }],
                    "volumes": [{"name": "tls", "secret": {"secretName": SECRET_NAME, "defaultMode": 0o440}}],
                },
            },
        },
    })
    run(*cluster.namespaced(namespace, "rollout", "status", f"deployment/{SERVICE_NAME}", "--timeout=90s"), limit=95)


def _reload_tls_server(cluster: ManagementCluster, namespace: str) -> None:
    run(*cluster.namespaced(namespace, "rollout", "restart", f"deployment/{SERVICE_NAME}"), limit=30)
    run(*cluster.namespaced(namespace, "rollout", "status", f"deployment/{SERVICE_NAME}", "--timeout=90s"), limit=95)


def _run_client_probe(
    cluster: ManagementCluster,
    namespace: str,
    pod_name: str,
    target_addr: str,
) -> dict[str, Any]:
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": pod_name, "namespace": namespace},
        "spec": {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [{
                "name": "probe",
                "image": TLS_IMAGE,
                "imagePullPolicy": "Never",
                "command": ["/tls-fixture", "probe", target_addr, EXPECTED_NAME, "/trust/ca.crt"],
                "volumeMounts": [{"name": "trust", "mountPath": "/trust", "readOnly": True}],
            }],
            "volumes": [{"name": "trust", "configMap": {"name": CA_CONFIGMAP_NAME}}],
        },
    })
    deadline = time.monotonic() + 75
    phase = ""
    while time.monotonic() < deadline:
        pod = cluster.read("get", "pod", pod_name, namespace=namespace)
        phase = pod.get("status", {}).get("phase", "")
        if phase in {"Succeeded", "Failed"}:
            break
        time.sleep(1)
    logs = ""
    try:
        logs = run(*cluster.namespaced(namespace, "logs", pod_name, "-c", "probe"), limit=25).strip()
    except subprocess.SubprocessError:
        logs = ""
    observation: dict[str, Any] = {}
    if logs:
        try:
            parsed = json.loads(logs)
            if isinstance(parsed, dict):
                observation = parsed
        except json.JSONDecodeError:
            observation = {"error": logs}
    banner = observation.pop("banner", None)
    raw_complete = observation.get("complete")
    if isinstance(raw_complete, bool):
        complete = phase == "Succeeded" and raw_complete
    else:
        complete = phase == "Succeeded" and banner == "ok\n" and bool(observation.get("leaf_sha256"))
    observation["complete"] = complete
    return observation


def _pack_warning_days() -> int:
    """Read the TLS warning window in days from the platform pack's admitted facts."""
    model = _committed()
    values: list[int] = []
    for path in facts.files(PLATFORM_PACK):
        rows = facts.load(model, path)
        for _, val in rows.get("tls_clock__warning_days", ()):
            if type(val) is int:
                values.append(val)
    if len(values) != 1:
        raise RuntimeError(f"Expected exactly one tls_clock__warning_days pack fact, got {values!r}")
    return values[0]


def _observed_dns_name(observation: dict[str, Any]) -> str:
    """Return the first non-empty observed leaf SAN DNS name from a probe observation."""
    for key in ("dns_names", "san_dns_names"):
        names = observation.get(key)
        if isinstance(names, list):
            for name in names:
                if isinstance(name, str) and name:
                    return name
    for key in ("leaf_dns_name", "presented_dns_name", "dns_name", "verified_dns_name"):
        val = observation.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _evaluate_management_rules(
    after: dict[str, Any],
    eval_day: str,
    trusted_root_sha256: str,
    warning_days: int,
) -> tuple[list[list[str]], list[list[str]]]:
    complete = bool(after.get("complete"))
    issuer_sha256 = str(after.get("issuer_sha256") or "")
    issuer_root_sha256 = str(after.get("issuer_root_sha256") or "")
    begins = str(after.get("begins") or "")
    ends = str(after.get("ends") or "")
    dns_name = _observed_dns_name(after)

    tls_issuer: list[dict[str, str]] = []
    if issuer_sha256 and issuer_root_sha256 and issuer_sha256 != issuer_root_sha256:
        tls_issuer.append({"id": issuer_sha256, "issuer": issuer_root_sha256})

    tls_leaf: list[dict[str, str]] = []
    if issuer_sha256 and begins and ends:
        tls_leaf.append({
            "id": "leaf-after",
            "service": "renewed",
            "read": "read-after",
            "dns_name": dns_name,
            "issuer": issuer_sha256,
            "begins": begins,
            "ends": ends,
        })

    records: dict[str, list[dict[str, Any]]] = {
        "tls_requirement": [{"id": "renewed", "caller": CALLER, "name": EXPECTED_NAME, "transport": "tls"}],
        "tls_clock": [{"id": "policy", "day": eval_day, "warning_days": warning_days}],
        "tls_root": [{"id": "client-trust", "caller": CALLER, "authority": trusted_root_sha256}],
        "tls_issuer": tls_issuer,
        "tls_read": [{"id": "read-after", "service": "renewed", "complete": complete}],
        "tls_leaf": tls_leaf,
    }
    _, state = compiled(records)
    findings = sorted(list(row) for row in state.derived.get("managed_tls_finding", set()))
    unknowns = sorted(list(row) for row in state.derived.get("managed_tls_unknown", set()))
    return findings, unknowns


def record_certificates() -> None:
    """Issue a local CA hierarchy, observe a TLS renewal in kind, evaluate rules, and record the Job."""
    cluster = ManagementCluster()
    trial_ns = f"rezono-cert-trial-{cluster.run}-{cluster.attempt}"
    cluster.wait("deployment/coredns", "--for=condition=Available", "--timeout=90s", namespace="kube-system", limit=95)

    warning_days = _pack_warning_days()
    now = datetime.now(timezone.utc)
    eval_day = now.strftime("%Y-%m-%d")
    ca_begins = datetime(now.year - 1, 1, 1, tzinfo=timezone.utc)
    ca_ends = datetime(now.year + 2, 12, 31, tzinfo=timezone.utc)
    inter_ends = datetime(now.year + 2, 6, 30, tzinfo=timezone.utc)
    leaf_begins = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    leaf1_ends = datetime(now.year + 1, 6, 30, tzinfo=timezone.utc)
    leaf2_ends = datetime(now.year + 1, 12, 31, tzinfo=timezone.utc)

    with TemporaryDirectory(dir=cluster.temp, prefix="rezono-tls-pki-") as directory:
        work_dir = Path(directory)
        root_key, root_cert = _build_ca("Rezono Fixture Root CA", ca_begins, ca_ends, path_length=1)
        inter_key, inter_cert = _build_ca(
            "Rezono Fixture Intermediate CA",
            ca_begins,
            inter_ends,
            path_length=0,
            issuer_cert=root_cert,
            issuer_key=root_key,
        )
        leaf1_key, leaf1_cert = _build_leaf(
            EXPECTED_NAME,
            leaf_begins,
            leaf1_ends,
            issuer_cert=inter_cert,
            issuer_key=inter_key,
        )
        leaf2_key, leaf2_cert = _build_leaf(
            EXPECTED_NAME,
            leaf_begins,
            leaf2_ends,
            issuer_cert=inter_cert,
            issuer_key=inter_key,
        )

        # Keep local PKI material in the temporary directory with owner-only permissions; never log keys.
        _write_secret_file(work_dir / "root.key", _key_pem(root_key))
        _write_secret_file(work_dir / "root.crt", _cert_pem(root_cert))
        _write_secret_file(work_dir / "intermediate.key", _key_pem(inter_key))
        _write_secret_file(work_dir / "intermediate.crt", _cert_pem(inter_cert))
        _write_secret_file(work_dir / "leaf1.key", _key_pem(leaf1_key))
        _write_secret_file(work_dir / "leaf1.crt", _cert_pem(leaf1_cert))
        _write_secret_file(work_dir / "leaf2.key", _key_pem(leaf2_key))
        _write_secret_file(work_dir / "leaf2.crt", _cert_pem(leaf2_cert))

        root_sha256 = _cert_sha256(root_cert)
        leaf1_sha256 = _cert_sha256(leaf1_cert)
        leaf2_sha256 = _cert_sha256(leaf2_cert)
        if leaf1_sha256 == leaf2_sha256:
            raise RuntimeError("Renewed leaf certificate must have a distinct SHA-256 fingerprint")

        _build_tls_image(cluster, work_dir)
        target_addr = f"{SERVICE_NAME}.{trial_ns}.svc.cluster.local:{SERVICE_PORT}"

        try:
            cluster.ensure_namespace(trial_ns, labels={"rezono.org/trial": FEATURE})
            cluster.apply({
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": CA_CONFIGMAP_NAME, "namespace": trial_ns},
                "data": {"ca.crt": _cert_pem(root_cert).decode("ascii")},
            })
            _apply_tls_secret(cluster, trial_ns, leaf1_cert, inter_cert, leaf1_key)
            _deploy_tls_server(cluster, trial_ns)

            before_obs = _run_client_probe(cluster, trial_ns, "tls-probe-before", target_addr)
            before_event = cluster.make_event(
                FEATURE,
                "tls-peer-observed",
                phase="before",
                caller=CALLER,
                expected_name=EXPECTED_NAME,
                **before_obs,
            )

            secret_rv = _apply_tls_secret(cluster, trial_ns, leaf2_cert, inter_cert, leaf2_key)
            _reload_tls_server(cluster, trial_ns)
            renewal_event = cluster.make_event(
                FEATURE,
                "renewal-applied",
                service="renewed",
                expected_name=EXPECTED_NAME,
                secret_name=SECRET_NAME,
                secret_resource_version=secret_rv,
                leaf_sha256=leaf2_sha256,
                issuer_root_sha256=root_sha256,
            )

            after_obs = _run_client_probe(cluster, trial_ns, "tls-probe-after", target_addr)
            after_event = cluster.make_event(
                FEATURE,
                "tls-peer-observed",
                phase="after",
                caller=CALLER,
                expected_name=EXPECTED_NAME,
                **after_obs,
            )
        finally:
            cluster.delete("namespace", trial_ns, "--wait=true", "--timeout=60s", limit=70)

    findings, unknowns = _evaluate_management_rules(after_obs, eval_day, root_sha256, warning_days)

    judgement_event = cluster.make_event(
        FEATURE,
        "renewal-judgement",
        service="renewed",
        source_evidence=after_event["evidence"],
        findings=findings,
        unknowns=unknowns,
        day=eval_day,
    )
    cluster.record_job(FEATURE, [before_event, renewal_event, after_event, judgement_event])


if __name__ == "__main__":
    record_certificates()
