"""Record real health probes and telemetry deliveries on the disposable cluster."""

from __future__ import annotations

import hashlib
from ipaddress import ip_address
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from management_recorder import ManagementCluster, run

ROOT = Path(__file__).resolve().parents[2]
for _extra in (ROOT / "examples", ROOT / "examples" / "platform" / "proof_cases"):
    _text = str(_extra)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from management_probes import compiled

HEALTH_IMAGE = "docker.io/library/rezono-health-fixture:local"
TELEMETRY_CHANNELS: tuple[tuple[str, int], ...] = (
    ("metrics", 4317),
    ("logs", 4318),
    ("alerts", 9443),
)
HEALTH_PORT = 8080

HEALTH_PROBE_GO = r"""// Static HTTP health responder, telemetry receiver, and HTTP probe for the disposable cluster.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type healthPayload struct {
	Service    string `json:"service"`
	Token      string `json:"token"`
	StatusCode int    `json:"status_code"`
	EventTime  int64  `json:"event_time"`
}

type deliveryRecord struct {
	Channel    string `json:"channel"`
	Port       int    `json:"port"`
	ReceivedAt int64  `json:"received_at"`
	Bytes      int    `json:"bytes"`
	SHA256     string `json:"sha256"`
	Payload    string `json:"payload"`
}

type probeOutput struct {
	URL        string `json:"url"`
	Reachable  bool   `json:"reachable"`
	StatusCode int    `json:"status_code,omitempty"`
	Body       string `json:"body,omitempty"`
	Error      string `json:"error,omitempty"`
	EventTime  int64  `json:"event_time"`
}

func writeJSON(w http.ResponseWriter, statusCode int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	_ = json.NewEncoder(w).Encode(value)
}

func serveHealth(args []string) error {
	if len(args) != 3 {
		return fmt.Errorf("usage: serve-health <port> <status-code> <service>")
	}
	port, err := strconv.Atoi(args[0])
	if err != nil || port < 1 || port > 65535 {
		return fmt.Errorf("invalid port %q", args[0])
	}
	statusCode, err := strconv.Atoi(args[1])
	if err != nil || statusCode < 100 || statusCode > 599 {
		return fmt.Errorf("invalid status code %q", args[1])
	}
	service := args[2]
	mux := http.NewServeMux()
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready\n"))
	})
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, statusCode, healthPayload{
			Service:    service,
			Token:      r.URL.Query().Get("token"),
			StatusCode: statusCode,
			EventTime:  time.Now().UTC().Unix(),
		})
	})
	server := &http.Server{
		Addr:              fmt.Sprintf(":%d", port),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	return server.ListenAndServe()
}

func serveTelemetry(args []string) error {
	if len(args) != 2 {
		return fmt.Errorf("usage: serve-telemetry <port> <channel>")
	}
	port, err := strconv.Atoi(args[0])
	if err != nil || port < 1 || port > 65535 {
		return fmt.Errorf("invalid port %q", args[0])
	}
	channel := args[1]
	var mu sync.Mutex
	var deliveries []deliveryRecord

	mux := http.NewServeMux()
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ready\n"))
	})
	mux.HandleFunc("/ingest", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		sum := sha256.Sum256(body)
		rec := deliveryRecord{
			Channel:    channel,
			Port:       port,
			ReceivedAt: time.Now().UTC().Unix(),
			Bytes:      len(body),
			SHA256:     hex.EncodeToString(sum[:]),
			Payload:    string(body),
		}
		mu.Lock()
		deliveries = append(deliveries, rec)
		mu.Unlock()
		fmt.Fprintf(os.Stdout, "received %s on :%d (%d bytes, sha256:%s)\n", channel, port, rec.Bytes, rec.SHA256)
		writeJSON(w, http.StatusOK, rec)
	})
	mux.HandleFunc("/deliveries", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		mu.Lock()
		snapshot := append([]deliveryRecord(nil), deliveries...)
		mu.Unlock()
		writeJSON(w, http.StatusOK, snapshot)
	})
	server := &http.Server{
		Addr:              fmt.Sprintf(":%d", port),
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	return server.ListenAndServe()
}

func probeHTTP(args []string) error {
	if len(args) != 1 {
		return fmt.Errorf("usage: probe-http <url>")
	}
	targetURL := args[0]
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(targetURL)
	if err != nil {
		return json.NewEncoder(os.Stdout).Encode(probeOutput{
			URL:       targetURL,
			Reachable: false,
			Error:     err.Error(),
			EventTime: time.Now().UTC().Unix(),
		})
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(probeOutput{
		URL:        targetURL,
		Reachable:  true,
		StatusCode: resp.StatusCode,
		Body:       string(body),
		EventTime:  time.Now().UTC().Unix(),
	})
}

func postJSON(args []string) error {
	if len(args) != 2 {
		return fmt.Errorf("usage: post-json <url> <json-payload>")
	}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Post(args[0], "application/json", strings.NewReader(args[1]))
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("unexpected HTTP status %d: %s", resp.StatusCode, string(body))
	}
	_, err = os.Stdout.Write(body)
	return err
}

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("expected serve-health, serve-telemetry, probe-http or post-json")
	}
	switch args[0] {
	case "serve-health":
		return serveHealth(args[1:])
	case "serve-telemetry":
		return serveTelemetry(args[1:])
	case "probe-http":
		return probeHTTP(args[1:])
	case "post-json":
		return postJSON(args[1:])
	default:
		return fmt.Errorf("unsupported command %q", args[0])
	}
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
"""


def ensure_health_image(cluster: ManagementCluster) -> None:
    """Compile the static Go health-probe binary and load its scratch image into kind."""
    with TemporaryDirectory(prefix="rezono-health-go-") as directory:
        source_path = Path(directory) / "health_probe.go"
        source_path.write_text(HEALTH_PROBE_GO, encoding="utf-8")
        cluster.build_go_image(source_path, HEALTH_IMAGE, "health-probe")


def apply_probe_pod(
    cluster: ManagementCluster,
    namespace: str,
    name: str,
    command: list[str],
    ready_port: int,
    labels: dict[str, str],
) -> None:
    """Schedule a locked-down pod running the static health-probe image."""
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "nodeName": cluster.node,
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 65534,
                "runAsGroup": 65534,
            },
            "containers": [{
                "name": "probe",
                "image": HEALTH_IMAGE,
                "imagePullPolicy": "Never",
                "command": command,
                "securityContext": {
                    "allowPrivilegeEscalation": False,
                    "capabilities": {"drop": ["ALL"]},
                },
                "readinessProbe": {
                    "httpGet": {"path": "/readyz", "port": ready_port},
                    "periodSeconds": 1,
                },
            }],
        },
    })


def pod_ip(cluster: ManagementCluster, namespace: str, name: str) -> str:
    """Return the validated pod IP for a ready workload in `namespace`."""
    return str(ip_address(cluster.read("get", "pod", name, namespace=namespace)["status"]["podIP"]))


def exec_collector(cluster: ManagementCluster, namespace: str, *args: str) -> str:
    """Run a probe or delivery command from inside the in-cluster collector pod."""
    return run(*cluster.namespaced(namespace, "exec", "health-collector", "--", "/health-probe", *args), limit=30)


def probe_endpoint(cluster: ManagementCluster, namespace: str, url: str) -> dict[str, Any]:
    """Perform a real HTTP GET from `health-collector` and parse its JSON probe result."""
    return json.loads(exec_collector(cluster, namespace, "probe-http", url))


def report_workloads(cluster: ManagementCluster, namespace: str) -> None:
    """Print pod statuses and logs in `namespace` before cleanup if the trial fails."""
    pods = cluster.read("get", "pods", namespace=namespace).get("items", [])
    for pod in pods:
        name = pod["metadata"]["name"]
        print(f"Health fixture pod {name}: {json.dumps(pod.get('status', {}), sort_keys=True)}", flush=True)
        logs = subprocess.run(
            cluster.namespaced(namespace, "logs", name),
            capture_output=True,
            text=True,
            timeout=20,
        )
        if logs.stdout:
            print(logs.stdout, flush=True)


def main() -> None:
    cluster = ManagementCluster()
    run_tag = f"{cluster.run}-{cluster.attempt}"
    temp_ns = f"rezono-health-{run_tag}"
    labels = {
        "rezono.org/management-feature": "health",
        "rezono.org/recorder-run": run_tag,
    }
    ensure_health_image(cluster)
    cluster.ensure_namespace(temp_ns, labels=labels)

    try:
        for channel, port in TELEMETRY_CHANNELS:
            apply_probe_pod(
                cluster,
                temp_ns,
                f"telemetry-{channel}",
                ["/health-probe", "serve-telemetry", str(port), channel],
                port,
                {**labels, "rezono.org/telemetry-channel": channel},
            )
        for service_name, status_code in (("well-service", 200), ("bad-service", 503), ("health-collector", 200)):
            apply_probe_pod(
                cluster,
                temp_ns,
                service_name,
                ["/health-probe", "serve-health", str(HEALTH_PORT), str(status_code), service_name],
                HEALTH_PORT,
                {**labels, "rezono.org/health-subject": service_name},
            )
        cluster.apply({
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "unreachable-cluster", "namespace": temp_ns, "labels": labels},
            "spec": {
                "selector": {"rezono.org/health-subject": "absent-unreachable-cluster"},
                "ports": [{"name": "http", "port": HEALTH_PORT, "targetPort": HEALTH_PORT}],
            },
        })

        cluster.wait("pods", "--all", "--for=condition=Ready", "--timeout=90s", namespace=temp_ns, limit=95)

        pod_ips = {
            name: pod_ip(cluster, temp_ns, name)
            for name in ("well-service", "bad-service", *(f"telemetry-{channel}" for channel, _ in TELEMETRY_CHANNELS))
        }
        unreachable_svc = cluster.read("get", "service", "unreachable-cluster", namespace=temp_ns)
        unreachable_ip = str(ip_address(unreachable_svc["spec"]["clusterIP"]))
        unreachable_ep = cluster.read("get", "endpoints", "unreachable-cluster", namespace=temp_ns)
        if unreachable_ep.get("subsets"):
            raise RuntimeError("Expected unreachable-cluster Service to have no active endpoints")

        tokens = {
            "well-service": f"health-{run_tag}-well",
            "bad-service": f"health-{run_tag}-bad",
            "unreachable-cluster": f"health-{run_tag}-unreachable",
        }
        targets = {
            "well-service": f"http://{pod_ips['well-service']}:{HEALTH_PORT}/healthz?token={tokens['well-service']}",
            "bad-service": f"http://{pod_ips['bad-service']}:{HEALTH_PORT}/healthz?token={tokens['bad-service']}",
            "unreachable-cluster": (
                f"http://{unreachable_ip}:{HEALTH_PORT}/healthz?token={tokens['unreachable-cluster']}"
            ),
        }

        probe_rows: list[dict[str, Any]] = []
        probe_details: dict[str, dict[str, Any]] = {}
        events: list[dict[str, Any]] = []

        for subject in ("well-service", "bad-service", "unreachable-cluster"):
            observed = probe_endpoint(cluster, temp_ns, targets[subject])
            if subject == "unreachable-cluster":
                if observed.get("reachable"):
                    raise RuntimeError(f"Expected unreachable-cluster probe to fail, got {observed}")
                probe_details[subject] = {
                    "target": targets[subject],
                    "reachable": False,
                    "error": observed["error"],
                }
                events.append(
                    cluster.make_event(
                        "health",
                        "health-probe",
                        subject=subject,
                        token=tokens[subject],
                        reachable=False,
                        error=observed["error"],
                        event_time=int(observed["event_time"]),
                    )
                )
                continue

            if not observed.get("reachable"):
                raise RuntimeError(f"Expected reachable probe for {subject}, got {observed}")
            body = json.loads(observed["body"])
            if body.get("service") != subject or body.get("token") != tokens[subject]:
                raise RuntimeError(f"Unexpected health payload for {subject}: {body}")
            status_code = int(observed["status_code"])
            event_time = int(body["event_time"])
            probe_id = f"probe-{subject}"
            probe_rows.append({
                "id": probe_id,
                "service": subject,
                "run": run_tag,
                "token": tokens[subject],
                "http_status": status_code,
                "event_time": event_time,
            })
            probe_details[subject] = {
                "target": targets[subject],
                "reachable": True,
                "http_status": status_code,
                "event_time": event_time,
            }
            events.append(
                cluster.make_event(
                    "health",
                    "health-probe",
                    id=probe_id,
                    subject=subject,
                    token=tokens[subject],
                    reachable=True,
                    http_status=status_code,
                    event_time=event_time,
                )
            )

        records = {
            "health_step": [
                {"id": subject, "service": subject, "run": run_tag, "token": tokens[subject]}
                for subject in ("well-service", "bad-service", "unreachable-cluster")
            ],
            "health_probe": probe_rows,
            "telemetry_cluster": [
                {"id": "work", "zone": "work"},
                {"id": "ops", "zone": "shared"},
            ],
            "telemetry_endpoint": [
                {"id": channel, "channel": channel, "zone": "shared", "port": port}
                for channel, port in TELEMETRY_CHANNELS
            ],
        }
        _, state = compiled(records)

        derived_health = sorted(state.derived.get("managed_health", ()))
        derived_complete = sorted(state.derived.get("managed_health_complete", ()))
        derived_finding = sorted(state.derived.get("managed_health_finding", ()))
        derived_routes = sorted(state.derived.get("managed_telemetry_firewall", ()))

        health_events: dict[str, dict[str, Any]] = {}
        for subject, derived_state, witness in derived_health:
            health_event = cluster.make_event(
                "health",
                "health",
                subject=subject,
                state=derived_state,
                witness=witness,
                token=tokens[subject],
                run_tag=run_tag,
                **probe_details[subject],
            )
            health_events[subject] = health_event
            events.append(health_event)

        for subject, witness in derived_complete:
            events.append(
                cluster.make_event(
                    "health",
                    "step-complete",
                    subject=subject,
                    token=tokens[subject],
                    witness=witness,
                    source_evidence=health_events[subject]["evidence"],
                )
            )

        for subject, witness in derived_finding:
            events.append(
                cluster.make_event(
                    "health",
                    "step-finding",
                    subject=subject,
                    token=tokens[subject],
                    witness=witness,
                    source_evidence=health_events[subject]["evidence"],
                )
            )

        channel_payloads = {
            "metrics": {
                "run": run_tag,
                "states": {subject: health_events[subject]["state"] for subject in sorted(health_events)},
            },
            "logs": {
                "run": run_tag,
                "observations": [
                    {"subject": subject, "evidence": health_events[subject]["evidence"]}
                    for subject in sorted(health_events)
                ],
            },
            "alerts": {
                "run": run_tag,
                "findings": [
                    {"subject": subject, "witness": witness}
                    for subject, witness in derived_finding
                ],
            },
        }

        for source_cluster, channel, port_text in derived_routes:
            port = int(port_text)
            receiver_name = f"telemetry-{channel}"
            receiver_ip = pod_ips[receiver_name]
            payload_text = json.dumps(channel_payloads[channel], sort_keys=True)
            expected_sha = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()

            receipt = json.loads(
                exec_collector(
                    cluster,
                    temp_ns,
                    "post-json",
                    f"http://{receiver_ip}:{port}/ingest",
                    payload_text,
                )
            )
            if receipt.get("channel") != channel or receipt.get("port") != port or receipt.get("sha256") != expected_sha:
                raise RuntimeError(f"Telemetry receipt mismatch for {channel}: {receipt}")

            readback = probe_endpoint(cluster, temp_ns, f"http://{receiver_ip}:{port}/deliveries")
            if not readback.get("reachable") or readback.get("status_code") != 200:
                raise RuntimeError(f"Failed to read deliveries from {receiver_name}: {readback}")
            deliveries = json.loads(readback["body"])
            matched = [item for item in deliveries if item.get("sha256") == expected_sha]
            if len(matched) != 1:
                raise RuntimeError(f"Expected 1 captured delivery for {channel}, got {deliveries}")
            captured = matched[0]
            events.append(
                cluster.make_event(
                    "health",
                    "collector-delivery",
                    channel=channel,
                    port=port,
                    source_cluster=source_cluster,
                    source_pod="health-collector",
                    receiver_pod=receiver_name,
                    receiver_ip=receiver_ip,
                    payload_sha256=captured["sha256"],
                    bytes_received=captured["bytes"],
                    received_at=captured["received_at"],
                )
            )

        cluster.record_job("health", events)
    except Exception:
        report_workloads(cluster, temp_ns)
        raise
    finally:
        cluster.delete("namespace", temp_ns, limit=90)


if __name__ == "__main__":
    main()
