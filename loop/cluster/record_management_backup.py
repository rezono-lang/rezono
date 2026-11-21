"""Record a real management backup, scale-down, unreachable probes, and isolated restore read."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic, sleep, time_ns
from typing import Any

from management_recorder import ManagementCluster, NAMESPACE as PROBE_NAMESPACE, ROOT, run

BACKUP_IMAGE = "docker.io/library/rezono-mgmt-backup-fixture:local"
STORE_NAMESPACE = "rezono-mgmt-store"
MGMT_NAMESPACE = "rezono-mgmt-plane"
RECOVERY_NAMESPACE = "rezono-mgmt-recovery"
STORE_POD = "rezono-mgmt-backup-store"
MGMT_DEPLOYMENT = "rezono-mgmt-plane"
PROBE_POD = "rezono-mgmt-probe"
RESTORE_JOB = "rezono-mgmt-restore"
SERVICE_PORT = 8080

GO_FIXTURE_SOURCE = r"""package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const maxObjectBytes = 1 << 20

type objectRecord struct {
	Key    string `json:"key"`
	SHA256 string `json:"sha256"`
	Size   int    `json:"size"`
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func validKey(key string) bool {
	if key == "" || strings.Contains(key, "/") || strings.Contains(key, "..") {
		return false
	}
	for _, r := range key {
		if !((r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') || r == '-' || r == '_' || r == '.') {
			return false
		}
	}
	return true
}

func serveStore(addr string) error {
	var mu sync.RWMutex
	objects := make(map[string][]byte)
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "ok\n")
	})
	mux.HandleFunc("/objects/", func(w http.ResponseWriter, r *http.Request) {
		key := strings.TrimPrefix(r.URL.Path, "/objects/")
		if !validKey(key) {
			http.Error(w, "invalid object key", http.StatusBadRequest)
			return
		}
		switch r.Method {
		case http.MethodPut:
			body, err := io.ReadAll(io.LimitReader(r.Body, maxObjectBytes+1))
			if err != nil {
				http.Error(w, err.Error(), http.StatusBadRequest)
				return
			}
			if len(body) > maxObjectBytes {
				http.Error(w, "object too large", http.StatusRequestEntityTooLarge)
				return
			}
			sum := sha256.Sum256(body)
			digest := hex.EncodeToString(sum[:])
			stored := append([]byte(nil), body...)
			mu.Lock()
			objects[key] = stored
			mu.Unlock()
			writeJSON(w, http.StatusCreated, objectRecord{Key: key, SHA256: digest, Size: len(stored)})
		case http.MethodGet:
			mu.RLock()
			data, ok := objects[key]
			mu.RUnlock()
			if !ok {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("Content-Type", "application/octet-stream")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write(data)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	})
	server := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	return server.ListenAndServe()
}

func serveMgmt(addr string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = io.WriteString(w, "ready\n")
	})
	server := &http.Server{Addr: addr, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	return server.ListenAndServe()
}

func putObject(storeURL, key string) error {
	if !validKey(key) {
		return fmt.Errorf("invalid key %q", key)
	}
	payload, err := io.ReadAll(io.LimitReader(os.Stdin, maxObjectBytes+1))
	if err != nil {
		return err
	}
	if len(payload) > maxObjectBytes {
		return fmt.Errorf("payload exceeds %d bytes", maxObjectBytes)
	}
	sum := sha256.Sum256(payload)
	expectedDigest := hex.EncodeToString(sum[:])
	target := strings.TrimRight(storeURL, "/") + "/objects/" + key
	client := &http.Client{Timeout: 10 * time.Second}

	var lastErr error
	for attempt := 0; attempt < 5; attempt++ {
		req, err := http.NewRequest(http.MethodPut, target, bytes.NewReader(payload))
		if err != nil {
			return err
		}
		resp, err := client.Do(req)
		if err != nil {
			lastErr = err
			time.Sleep(500 * time.Millisecond)
			continue
		}
		body, readErr := io.ReadAll(resp.Body)
		resp.Body.Close()
		if readErr != nil {
			lastErr = readErr
			time.Sleep(500 * time.Millisecond)
			continue
		}
		if resp.StatusCode != http.StatusCreated {
			return fmt.Errorf("unexpected store status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
		}
		var rec objectRecord
		if err := json.Unmarshal(body, &rec); err != nil {
			return err
		}
		if rec.SHA256 != expectedDigest || rec.Size != len(payload) {
			return fmt.Errorf("store digest mismatch: got %s (%d), want %s (%d)", rec.SHA256, rec.Size, expectedDigest, len(payload))
		}
		return json.NewEncoder(os.Stdout).Encode(rec)
	}
	return lastErr
}

func probeEndpoint(host, port string) error {
	addr := net.JoinHostPort(host, port)
	conn, err := net.DialTimeout("tcp4", addr, 2*time.Second)
	result := map[string]any{"address": addr}
	if err != nil {
		result["reachable"] = false
		result["error"] = err.Error()
		return json.NewEncoder(os.Stdout).Encode(result)
	}
	_ = conn.Close()
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://" + addr + "/healthz")
	if err != nil {
		result["reachable"] = false
		result["error"] = err.Error()
		return json.NewEncoder(os.Stdout).Encode(result)
	}
	resp.Body.Close()
	result["reachable"] = resp.StatusCode == http.StatusOK
	result["status"] = resp.StatusCode
	return json.NewEncoder(os.Stdout).Encode(result)
}

func restoreRead(storeURL, key, mgmtHost, mgmtPort string) error {
	if !validKey(key) {
		return fmt.Errorf("invalid key %q", key)
	}
	mgmtAddr := net.JoinHostPort(mgmtHost, mgmtPort)
	conn, mgmtErr := net.DialTimeout("tcp4", mgmtAddr, 2*time.Second)
	if mgmtErr == nil {
		_ = conn.Close()
		return fmt.Errorf("management endpoint %s unexpectedly reachable from isolated recovery", mgmtAddr)
	}

	target := strings.TrimRight(storeURL, "/") + "/objects/" + key
	client := &http.Client{Timeout: 10 * time.Second}
	var lastErr error
	for attempt := 0; attempt < 5; attempt++ {
		resp, err := client.Get(target)
		if err != nil {
			lastErr = err
			time.Sleep(500 * time.Millisecond)
			continue
		}
		data, readErr := io.ReadAll(io.LimitReader(resp.Body, maxObjectBytes+1))
		resp.Body.Close()
		if readErr != nil {
			lastErr = readErr
			time.Sleep(500 * time.Millisecond)
			continue
		}
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("store read status %d: %s", resp.StatusCode, strings.TrimSpace(string(data)))
		}
		sum := sha256.Sum256(data)
		out := map[string]any{
			"key":             key,
			"sha256":          hex.EncodeToString(sum[:]),
			"size":            len(data),
			"mgmt_dial_error": mgmtErr.Error(),
			"isolated":        true,
		}
		return json.NewEncoder(os.Stdout).Encode(out)
	}
	return lastErr
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: backup-fixture <store|mgmt|put|probe|restore-read> ...")
		os.Exit(1)
	}
	var err error
	switch os.Args[1] {
	case "store":
		if len(os.Args) != 3 {
			err = fmt.Errorf("usage: store <listen-addr>")
		} else {
			err = serveStore(os.Args[2])
		}
	case "mgmt":
		if len(os.Args) != 3 {
			err = fmt.Errorf("usage: mgmt <listen-addr>")
		} else {
			err = serveMgmt(os.Args[2])
		}
	case "put":
		if len(os.Args) != 4 {
			err = fmt.Errorf("usage: put <store-url> <key>")
		} else {
			err = putObject(os.Args[2], os.Args[3])
		}
	case "probe":
		if len(os.Args) != 4 {
			err = fmt.Errorf("usage: probe <host> <port>")
		} else {
			err = probeEndpoint(os.Args[2], os.Args[3])
		}
	case "restore-read":
		if len(os.Args) != 6 {
			err = fmt.Errorf("usage: restore-read <store-url> <key> <mgmt-host> <mgmt-port>")
		} else {
			err = restoreRead(os.Args[2], os.Args[3], os.Args[4], os.Args[5])
		}
	default:
		err = fmt.Errorf("unsupported command %q", os.Args[1])
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
"""


def _ensure_backup_image(cluster: ManagementCluster) -> None:
    with TemporaryDirectory(prefix="rezono-mgmt-backup-") as directory:
        source = Path(directory) / "backup_fixture.go"
        source.write_text(GO_FIXTURE_SOURCE, encoding="utf-8")
        cluster.build_go_image(source, BACKUP_IMAGE, "backup-fixture")


def _labels(cluster: ManagementCluster, role: str, app: str) -> dict[str, str]:
    return {
        "rezono.org/backup-trial": f"{cluster.run}-{cluster.attempt}",
        "rezono.org/backup-role": role,
        "app": app,
    }


def _deploy_store(cluster: ManagementCluster) -> str:
    cluster.ensure_namespace(STORE_NAMESPACE, {"rezono.org/backup-role": "store"})
    labels = _labels(cluster, "store", STORE_POD)
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": STORE_POD, "namespace": STORE_NAMESPACE, "labels": labels},
        "spec": {
            "nodeName": cluster.node,
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [{
                "name": "store",
                "image": BACKUP_IMAGE,
                "imagePullPolicy": "Never",
                "command": ["/backup-fixture", "store", f":{SERVICE_PORT}"],
                "ports": [{"containerPort": SERVICE_PORT, "protocol": "TCP"}],
                "readinessProbe": {
                    "httpGet": {"path": "/healthz", "port": SERVICE_PORT},
                    "periodSeconds": 1,
                },
            }],
        },
    })
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": STORE_POD, "namespace": STORE_NAMESPACE, "labels": labels},
        "spec": {
            "selector": {"app": STORE_POD},
            "ports": [{"name": "http", "port": SERVICE_PORT, "targetPort": SERVICE_PORT, "protocol": "TCP"}],
        },
    })
    cluster.wait(f"pod/{STORE_POD}", "--for=condition=Ready", "--timeout=60s", namespace=STORE_NAMESPACE, limit=70)
    return f"http://{STORE_POD}.{STORE_NAMESPACE}.svc.cluster.local:{SERVICE_PORT}"


def _deploy_management(cluster: ManagementCluster) -> tuple[str, str]:
    cluster.ensure_namespace(MGMT_NAMESPACE, {"rezono.org/backup-role": "management"})
    labels = _labels(cluster, "management", MGMT_DEPLOYMENT)
    cluster.apply({
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": MGMT_DEPLOYMENT, "namespace": MGMT_NAMESPACE, "labels": labels},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": MGMT_DEPLOYMENT}},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeName": cluster.node,
                    "automountServiceAccountToken": False,
                    "containers": [{
                        "name": "mgmt",
                        "image": BACKUP_IMAGE,
                        "imagePullPolicy": "Never",
                        "command": ["/backup-fixture", "mgmt", f":{SERVICE_PORT}"],
                        "ports": [{"containerPort": SERVICE_PORT, "protocol": "TCP"}],
                        "readinessProbe": {
                            "httpGet": {"path": "/healthz", "port": SERVICE_PORT},
                            "periodSeconds": 1,
                        },
                    }],
                },
            },
        },
    })
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": MGMT_DEPLOYMENT, "namespace": MGMT_NAMESPACE, "labels": labels},
        "spec": {
            "selector": {"app": MGMT_DEPLOYMENT},
            "ports": [{"name": "http", "port": SERVICE_PORT, "targetPort": SERVICE_PORT, "protocol": "TCP"}],
        },
    })
    cluster.wait(
        f"deployment/{MGMT_DEPLOYMENT}",
        "--for=condition=Available",
        "--timeout=60s",
        namespace=MGMT_NAMESPACE,
        limit=70,
    )
    pods = cluster.read("get", "pods", "-l", f"app={MGMT_DEPLOYMENT}", namespace=MGMT_NAMESPACE)["items"]
    pod_name, = [
        p["metadata"]["name"]
        for p in pods
        if any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", []))
    ]
    service = cluster.read("get", "service", MGMT_DEPLOYMENT, namespace=MGMT_NAMESPACE)
    cluster_ip = service["spec"]["clusterIP"]
    return pod_name, cluster_ip


def _deploy_probe_pod(cluster: ManagementCluster) -> str:
    cluster.ensure_namespace(PROBE_NAMESPACE)
    labels = _labels(cluster, "probe", PROBE_POD)
    cluster.apply({
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": PROBE_POD, "namespace": PROBE_NAMESPACE, "labels": labels},
        "spec": {
            "nodeName": cluster.node,
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "containers": [{
                "name": "probe",
                "image": BACKUP_IMAGE,
                "imagePullPolicy": "Never",
                "command": ["/backup-fixture", "mgmt", ":8081"],
                "readinessProbe": {"httpGet": {"path": "/healthz", "port": 8081}, "periodSeconds": 1},
            }],
        },
    })
    cluster.wait(f"pod/{PROBE_POD}", "--for=condition=Ready", "--timeout=60s", namespace=PROBE_NAMESPACE, limit=70)
    return PROBE_POD


def _setup_recovery_namespace(cluster: ManagementCluster) -> None:
    cluster.ensure_namespace(RECOVERY_NAMESPACE, {"rezono.org/backup-role": "recovery"})
    cluster.apply({
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "default-deny-all", "namespace": RECOVERY_NAMESPACE},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Ingress", "Egress"],
        },
    })
    cluster.apply({
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "allow-object-store-egress", "namespace": RECOVERY_NAMESPACE},
        "spec": {
            "podSelector": {},
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [{
                        "namespaceSelector": {"matchLabels": {"rezono.org/backup-role": "store"}},
                        "podSelector": {"matchLabels": {"app": STORE_POD}},
                    }],
                    "ports": [{"protocol": "TCP", "port": SERVICE_PORT}],
                },
                {
                    "to": [{
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                        "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                    }],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
            ],
        },
    })


def _probe_management(cluster: ManagementCluster, probe_pod: str, host: str, port: int) -> dict[str, Any]:
    raw = run(
        *cluster.namespaced(
            PROBE_NAMESPACE,
            "exec",
            probe_pod,
            "--",
            "/backup-fixture",
            "probe",
            host,
            str(port),
        ),
        limit=20,
    )
    return json.loads(raw)


def _scale_down_management(cluster: ManagementCluster) -> None:
    run(*cluster.namespaced(MGMT_NAMESPACE, "scale", f"deployment/{MGMT_DEPLOYMENT}", "--replicas=0"), limit=30)
    cluster.wait(
        "pods",
        "-l",
        f"app={MGMT_DEPLOYMENT}",
        "--for=delete",
        "--timeout=60s",
        namespace=MGMT_NAMESPACE,
        limit=70,
    )
    deadline = monotonic() + 30.0
    while monotonic() < deadline:
        slices = cluster.read(
            "get",
            "endpointslices",
            "-l",
            f"kubernetes.io/service-name={MGMT_DEPLOYMENT}",
            namespace=MGMT_NAMESPACE,
        ).get("items", [])
        ready = [
            ep
            for sl in slices
            for ep in (sl.get("endpoints") or [])
            if ep.get("conditions", {}).get("ready") is True
        ]
        if not ready:
            return
        sleep(0.5)
    raise RuntimeError("Management service endpoints stayed ready after scale-down")


DATASET = "management-catalog"


class ManagementFence:
    """Keep the stopped management plane fenced and watch its namespace for any Pod over the whole interval."""

    def __init__(self, cluster: ManagementCluster, name: str) -> None:
        self.cluster, self.name = cluster, name
        _scale_down_management(cluster)
        cluster.apply({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": name, "namespace": MGMT_NAMESPACE,
                         "labels": {"rezono.org/management-fence": name}},
            "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]},
        })
        # A list-then-watch from this moment on: any Pod in the management namespace breaks the fence.
        self.watch = subprocess.Popen(
            [*cluster.namespaced(MGMT_NAMESPACE, "get", "pods", "--watch", "--output-watch-events", "-o", "json"),
             "--request-timeout=0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        sleep(2)
        if self.watch.poll() is not None:
            raise RuntimeError(f"The management fence watch ended at once: {self.watch.stderr.read()}")
        self.state = self.read_state()
        if self.state["replicas"] != 0 or self.state["ready_endpoints"]:
            raise RuntimeError(f"The management plane is not stopped under the fence: {self.state}")

    def read_state(self) -> dict[str, Any]:
        deployment = self.cluster.read("get", "deployment", MGMT_DEPLOYMENT, namespace=MGMT_NAMESPACE)
        policy = self.cluster.read("get", "networkpolicy", self.name, namespace=MGMT_NAMESPACE)
        slices = self.cluster.read("get", "endpointslices", "-l", f"kubernetes.io/service-name={MGMT_DEPLOYMENT}",
                                   namespace=MGMT_NAMESPACE).get("items", [])
        pods = self.cluster.read("get", "pods", namespace=MGMT_NAMESPACE).get("items", [])
        return {
            "replicas": deployment["spec"]["replicas"],
            "deployment_generation": deployment["metadata"]["generation"],
            "policy_uid": policy["metadata"]["uid"],
            "policy_resource_version": policy["metadata"]["resourceVersion"],
            "ready_endpoints": [ep for sl in slices for ep in (sl.get("endpoints") or [])
                                if ep.get("conditions", {}).get("ready") is True],
            "pods": [pod["metadata"]["name"] for pod in pods],
        }

    def release(self) -> tuple[int, int]:
        """Stop the watch and return (watched Pod events, lost watch intervals)."""
        alive = self.watch.poll() is None
        self.watch.terminate()
        output, errors = self.watch.communicate(timeout=10)
        decoder, position, seen = json.JSONDecoder(), 0, 0
        text = output.strip()
        while position < len(text):
            item, end = decoder.raw_decode(text, position)
            if item.get("object", {}).get("kind") == "Pod":
                seen += 1
            position = end
            while position < len(text) and text[position].isspace():
                position += 1
        # kubectl reports an empty initial list on stderr; anything else means the watch lost its stream.
        failures = [line for line in errors.splitlines() if line.strip() and not line.startswith("No resources found")]
        return seen, 0 if alive and not failures else 1

    def close(self) -> None:
        if self.watch.poll() is None:
            self.watch.kill()
            self.watch.communicate(timeout=10)


def _run_isolated_restore_read(
    cluster: ManagementCluster,
    store_url: str,
    object_key: str,
    mgmt_host: str,
    mgmt_port: int,
) -> dict[str, Any]:
    labels = _labels(cluster, "recovery", RESTORE_JOB)
    cluster.apply({
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": RESTORE_JOB, "namespace": RECOVERY_NAMESPACE, "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 45,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "nodeName": cluster.node,
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "containers": [{
                        "name": "restore",
                        "image": BACKUP_IMAGE,
                        "imagePullPolicy": "Never",
                        "command": [
                            "/backup-fixture",
                            "restore-read",
                            store_url,
                            object_key,
                            mgmt_host,
                            str(mgmt_port),
                        ],
                    }],
                },
            },
        },
    })
    cluster.wait(f"job/{RESTORE_JOB}", "--for=condition=Complete", "--timeout=60s", namespace=RECOVERY_NAMESPACE, limit=70)
    job = cluster.read("get", "job", RESTORE_JOB, namespace=RECOVERY_NAMESPACE)
    pods = cluster.read("get", "pods", "-l", f"job-name={RESTORE_JOB}", namespace=RECOVERY_NAMESPACE)["items"]
    pod, = [
        p
        for p in pods
        if p["status"]["phase"] == "Succeeded"
        and any(o["uid"] == job["metadata"]["uid"] and o["controller"] for o in p["metadata"]["ownerReferences"])
    ]
    logs = run(*cluster.namespaced(RECOVERY_NAMESPACE, "logs", pod["metadata"]["name"], "-c", "restore"), limit=20)
    return json.loads(logs)


def _evaluate_backup_rules(records: dict[str, list[dict[str, Any]]]) -> dict[str, set[tuple[str, ...]]]:
    from rezono_compiler import batch, facts, pack, rules, scenarios

    model = pack.read(ROOT / "examples" / "platform")
    program = rules.load(model.rules)
    rule_inputs = scenarios.rule_rows(model, program, facts.rows_of(model, records))
    targets = ("managed_backup_state", "managed_backup_restored", "managed_backup_route")
    derived_set = set(program.derived())
    needed: set[str] = set()
    stack = list(targets)
    while stack:
        rel = stack.pop()
        if rel in needed:
            continue
        needed.add(rel)
        stack.extend(dep for dep in program.deps(rel) if dep in derived_set and dep not in needed)
    with batch.connect(program, rule_inputs) as con:
        batch.compute(con, program, relations=needed)
        return batch.read(con, program, targets)


def _eligibility_records(today: str, run_key: str, backup_id: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "backup_decision": [{"id": "daily", "as_of": today, "max_age_days": 2}],
        "backup_plan": [{
            "id": "management-backup-plan",
            "service": "management",
            "dataset": DATASET,
            "target": STORE_POD,
            "decided_by": "daily",
            "interval_days": 1,
            "retention_days": 14,
        }],
        "backup_inventory": [{
            "id": f"scan-{run_key}",
            "service": "management",
            "target": STORE_POD,
            "day": today,
            "complete": True,
        }],
        "backup_copy": [{"id": backup_id, "service": "management", "target": STORE_POD, "taken": today}],
    }


def _cleanup_trial_resources(cluster: ManagementCluster) -> None:
    cluster.delete("pod", PROBE_POD, namespace=PROBE_NAMESPACE, limit=45)
    for namespace in (RECOVERY_NAMESPACE, MGMT_NAMESPACE, STORE_NAMESPACE):
        cluster.delete("namespace", namespace, limit=60)


def main() -> None:
    cluster = ManagementCluster()
    _ensure_backup_image(cluster)

    run_key = f"{cluster.run}-{cluster.attempt}"
    backup_id = f"management-copy-{run_key}"
    trial_id = f"management-trial-{run_key}"
    object_key = f"marker-{run_key}.txt"
    payload_text = f"rezono management backup marker run={cluster.run} attempt={cluster.attempt} ns={time_ns()}\n"
    expected_sha256 = sha256(payload_text.encode("utf-8")).hexdigest()
    store_host_endpoint = f"{STORE_POD}.{STORE_NAMESPACE}.svc.cluster.local:{SERVICE_PORT}"

    events: list[dict[str, Any]] = []
    stack_fence: ManagementFence | None = None
    try:
        store_url = _deploy_store(cluster)
        mgmt_pod, mgmt_cluster_ip = _deploy_management(cluster)
        probe_pod = _deploy_probe_pod(cluster)
        _setup_recovery_namespace(cluster)

        pre_probe = _probe_management(cluster, probe_pod, mgmt_cluster_ip, SERVICE_PORT)
        if not pre_probe.get("reachable"):
            raise RuntimeError(f"Expected management endpoint to be reachable before scale-down: {pre_probe}")

        upload_raw = run(
            *cluster.namespaced(
                MGMT_NAMESPACE,
                "exec",
                "-i",
                mgmt_pod,
                "--",
                "/backup-fixture",
                "put",
                store_url,
                object_key,
            ),
            data=payload_text,
            limit=30,
        )
        upload = json.loads(upload_raw)
        if upload["sha256"] != expected_sha256 or upload["size"] != len(payload_text.encode("utf-8")):
            raise RuntimeError(f"Uploaded payload verification failed: {upload}")

        captured = cluster.make_event(
            "backup",
            "backup-completed",
            backup=backup_id,
            source_cluster="management",
            payload_sha256=upload["sha256"],
            trial=trial_id,
            store=STORE_POD,
            object_key=object_key,
            size=upload["size"],
        )
        events.append(captured)

        # Before the outage: bind the named dataset to this exact copy after the decision finds it current.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        eligibility = _evaluate_backup_rules(_eligibility_records(today, run_key, backup_id))
        if eligibility["managed_backup_state"] != {("management-backup-plan", "current")}:
            raise RuntimeError(f"The captured copy is not current: {eligibility['managed_backup_state']}")
        binding = cluster.make_event(
            "backup",
            "management-dataset-bound",
            trial=trial_id,
            dataset=DATASET,
            backup=backup_id,
            source_cluster="management",
            source_evidence=captured["evidence"],
            payload_sha256=captured["payload_sha256"],
            backup_state="current",
            decision="daily",
        )
        events.append(binding)

        fence = ManagementFence(cluster, f"management-fence-{run_key}")
        stack_fence = fence
        hold = cluster.make_event(
            "backup",
            "management-fence-acquired",
            trial=trial_id,
            cluster="management",
            fence=fence.name,
            **{key: value for key, value in fence.state.items() if key != "ready_endpoints"},
        )
        events.append(hold)

        opening = _probe_management(cluster, probe_pod, mgmt_cluster_ip, SERVICE_PORT)
        if opening.get("reachable") is not False:
            raise RuntimeError(f"Expected management to be unreachable at opening probe: {opening}")
        opening_event = cluster.make_event(
            "backup",
            "management-unreachable",
            cluster="management",
            probe_result="unreachable",
            trial=trial_id,
            phase="opening",
            detail=opening.get("error", ""),
        )
        events.append(opening_event)

        readback_result = _run_isolated_restore_read(cluster, store_url, object_key, mgmt_cluster_ip, SERVICE_PORT)
        if (
            readback_result["sha256"] != expected_sha256
            or readback_result["size"] != len(payload_text.encode("utf-8"))
            or not readback_result.get("mgmt_dial_error")
            or readback_result.get("isolated") is not True
        ):
            raise RuntimeError(f"Isolated recovery readback mismatch: {readback_result}")

        readback = cluster.make_event(
            "backup",
            "recovered-read",
            backup=backup_id,
            dataset=DATASET,
            cluster="recovery",
            trial=trial_id,
            source_evidence=captured["evidence"],
            payload_sha256=readback_result["sha256"],
            isolated=True,
            active_authority=False,
        )
        events.append(readback)

        closing = _probe_management(cluster, probe_pod, mgmt_cluster_ip, SERVICE_PORT)
        if closing.get("reachable") is not False:
            raise RuntimeError(f"Expected management to be unreachable at closing probe: {closing}")
        closing_event = cluster.make_event(
            "backup",
            "management-unreachable",
            cluster="management",
            probe_result="unreachable",
            trial=trial_id,
            phase="closing",
            detail=closing.get("error", ""),
        )
        events.append(closing_event)

        watched, lost = fence.release()
        after = fence.read_state()
        unchanged = all(after[key] == fence.state[key] for key in
                        ("replicas", "deployment_generation", "policy_uid", "policy_resource_version", "pods"))
        if watched or lost or not unchanged or after["ready_endpoints"]:
            raise RuntimeError(f"The management fence did not hold: watched={watched} lost={lost} after={after}")
        events.append(cluster.make_event(
            "backup",
            "management-fence-coverage",
            trial=trial_id,
            cluster="management",
            fence=fence.name,
            fence_evidence=hold["evidence"],
            complete=True,
            lost=lost,
            watched_pod_events=watched,
            start=hold["observed_at"],
            end=closing_event["observed_at"],
            opening_probe=opening_event["evidence"],
            closing_probe=closing_event["evidence"],
            readback_evidence=readback["evidence"],
        ))
    finally:
        if stack_fence is not None:
            stack_fence.close()
        _cleanup_trial_resources(cluster)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    derived = _evaluate_backup_rules({
        "backup_decision": [{"id": "daily", "as_of": today, "max_age_days": 2}],
        "backup_plan": [{
            "id": "management-backup-plan",
            "service": "management",
            "dataset": "management-catalog",
            "target": STORE_POD,
            "decided_by": "daily",
            "interval_days": 1,
            "retention_days": 14,
        }],
        "backup_inventory": [{
            "id": f"scan-{run_key}",
            "service": "management",
            "target": STORE_POD,
            "day": today,
            "complete": True,
        }],
        "backup_copy": [{
            "id": backup_id,
            "service": "management",
            "target": STORE_POD,
            "taken": today,
        }],
        "backup_trial": [{
            "id": trial_id,
            "backup": backup_id,
            "cluster": "recovery",
            "run": run_key,
        }],
        "backup_capture": [{
            "id": captured["evidence"],
            "backup": backup_id,
            "source_cluster": "management",
            "run": run_key,
            "payload_sha256": captured["payload_sha256"],
        }],
        "backup_readback": [{
            "id": readback["evidence"],
            "backup": backup_id,
            "cluster": "recovery",
            "run": run_key,
            "trial": trial_id,
            "source_evidence": captured["evidence"],
            "payload_sha256": readback["payload_sha256"],
        }],
        "backup_site": [
            {"id": "management", "function": "producer"},
            {"id": "recovery", "function": "recovery"},
        ],
        "backup_store": [{
            "id": STORE_POD,
            "endpoint": store_host_endpoint,
        }],
    })
    if derived["managed_backup_state"] != {("management-backup-plan", "current")}:
        raise RuntimeError(f"Unexpected managed_backup_state: {derived['managed_backup_state']}")
    if derived["managed_backup_restored"] != {(backup_id, trial_id)}:
        raise RuntimeError(f"Unexpected managed_backup_restored: {derived['managed_backup_restored']}")
    expected_routes = {
        ("management", store_host_endpoint, "write"),
        ("recovery", store_host_endpoint, "read"),
    }
    if derived["managed_backup_route"] != expected_routes:
        raise RuntimeError(f"Unexpected managed_backup_route: {derived['managed_backup_route']}")

    cluster.record_job("backup", events)


if __name__ == "__main__":
    main()
