"""Record two actual network sweeps in the single disposable cluster."""

from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
from ipaddress import IPv4Address, ip_address
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import sleep, time_ns
from urllib.parse import urlsplit

from network_hubble import Hubble
from network_router import Router, transit


ROOT = Path(__file__).resolve().parents[2]
CONTEXT = "kind-rezono-fixture"
NAMESPACE = "rezono-probes"
FIXTURE = ROOT / "loop/tests/fixtures/network.json"
MARKER_PORT = 8090


def run(*args: str, data: str | None = None, limit: int = 25, env: dict | None = None) -> str:
    return subprocess.run(args, input=data, check=True, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE, timeout=limit, env=env).stdout


class Cluster:
    def __init__(self, env: dict[str, str]):
        self.run, self.attempt = env["GITHUB_RUN_ID"], env["GITHUB_RUN_ATTEMPT"]
        if not all(n.isascii() and n.isdecimal() for n in (self.run, self.attempt)):
            raise ValueError("The recorder needs the real runner's numeric run and attempt")
        self.label = {"rezono-fixture-network": f"{self.run}-{self.attempt}"}
        self.job = f"record-network-{self.run}-{self.attempt}"
        temp = Path(env["RUNNER_TEMP"]).resolve(strict=True)
        config = Path(env["REZONO_CLUSTER_KUBECONFIG"]).resolve(strict=True)
        if not config.is_relative_to(temp) or not config.samefile(env["REZONO_ADMISSION_TEST_KUBECONFIG"]):
            raise RuntimeError("The fixture must use the current run's shared admission kubeconfig")
        base = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
        if run(*base, "config", "current-context").strip() != CONTEXT:
            raise RuntimeError("The fixture kubeconfig has an unexpected current context")
        server = run(*base, "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        if not ip_address(urlsplit(server).hostname).is_loopback:
            raise RuntimeError("The fixture API server must be runner-local")
        self.command = [*base, "--context", CONTEXT]
        nodes = self.read("get", "nodes")["items"]
        kind_nodes = run("kind", "get", "nodes", "--name", "rezono-fixture").split()
        if len(kind_nodes) != 1 or {node["metadata"]["name"] for node in nodes} != set(kind_nodes):
            raise RuntimeError("The recorder requires the single pinned local kind node")
        self.node, = kind_nodes
        self.image = "docker.io/library/rezono-network-fixture:local"
        self.cilium = self._cilium()

    def namespaced(self, namespace: str, *args: str) -> list[str]:
        return [*self.command, "-n", namespace, *args]

    def read(self, *args: str, namespace: str | None = None) -> dict:
        command = self.namespaced(namespace, *args) if namespace else [*self.command, *args]
        return json.loads(run(*command, "-o", "json"))

    def apply(self, manifest: dict) -> None:
        run(*self.command, "apply", "-f", "-", data=json.dumps(manifest))

    def pod_ip(self, endpoint: str) -> str:
        return str(IPv4Address(self.read("get", "pod", endpoint, namespace=NAMESPACE)["status"]["podIP"]))

    def _cilium(self) -> str:
        pods = self.read("get", "pods", "-l", "k8s-app=cilium", namespace="kube-system")["items"]
        candidates = [pod["metadata"]["name"] for pod in pods if pod["spec"]["nodeName"] == self.node
                      and any(c["type"] == "Ready" and c["status"] == "True"
                              for c in pod["status"].get("conditions", []))]
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one ready Cilium agent on the fixture node")
        return candidates[0]

    def hubble(self) -> Hubble:
        # The node agent's Unix socket gives the original node stream, including loss records.
        command = [*self.command, "-n", "kube-system", "exec", self.cilium, "-c", "cilium-agent", "--",
                   "hubble", "observe", "--server", "unix:///var/run/cilium/hubble.sock",
                   "--follow", "--output", "jsonpb"]
        return Hubble(command)

    def node_pid(self, name: str) -> str:
        label = run("docker", "inspect", "-f", '{{index .Config.Labels "io.x-k8s.kind.cluster"}}', name).strip()
        if label != "rezono-fixture":
            raise RuntimeError("The transit destination is not owned by the named kind fixture")
        pid = run("docker", "inspect", "-f", "{{.State.Pid}}", name).strip()
        if not pid.isdecimal() or int(pid) < 2:
            raise RuntimeError("The local kind node is not running")
        return pid

    def clean_workloads(self) -> None:
        selected = ",".join(f"{key}={value}" for key, value in self.label.items())
        run(*self.namespaced(NAMESPACE, "delete", "pod,networkpolicy", "-l", selected, "--ignore-not-found",
                             "--wait=true", "--timeout=25s"), limit=30)

    def record(self, events: list[dict]) -> None:
        payload = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        config = f"{self.job}-evidence"
        self.apply({
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": config, "namespace": NAMESPACE, "labels": self.label},
            "immutable": True, "data": {"observed.jsonl": payload},
        })
        self.apply({
            "apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": self.job, "namespace": NAMESPACE, "labels": self.label},
            "spec": {
                "backoffLimit": 0, "activeDeadlineSeconds": 40,
                "template": {"spec": {
                    "restartPolicy": "Never", "automountServiceAccountToken": False,
                    "containers": [{
                        "name": "recorder", "image": self.image, "imagePullPolicy": "Never",
                        "command": ["/network-probe", "record", "/evidence/observed.jsonl"],
                        "volumeMounts": [{"name": "observations", "mountPath": "/evidence", "readOnly": True}],
                    }],
                    "volumes": [{"name": "observations", "configMap": {"name": config}}],
                }},
            },
        })
        run(*self.namespaced(NAMESPACE, "wait", f"job/{self.job}", "--for=condition=Complete", "--timeout=45s"),
            limit=50)


def start_services(cluster: Cluster, matrix: dict) -> dict[str, str]:

    ports = {}
    for case in matrix["cases"]:
        if case["protocol"] != "TCP":
            raise ValueError("This fixture only starts TCP listeners")
        ports.setdefault(case["destination"], set()).add(case["port"])
    for endpoint, listened in sorted(ports.items()):
        cluster.apply({
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": endpoint, "namespace": NAMESPACE,
                         "labels": {**cluster.label, "rezono-network-endpoint": endpoint}},
            "spec": {
                "nodeName": cluster.node, "automountServiceAccountToken": False, "restartPolicy": "Never",
                "containers": [{
                    "name": "listener", "image": cluster.image, "imagePullPolicy": "Never",
                    "command": ["/network-probe", "serve", *(str(port) for port in sorted(listened))],
                    "readinessProbe": {"tcpSocket": {"port": min(listened)}, "periodSeconds": 1},
                }],
            },
        })
    run(*cluster.namespaced(NAMESPACE, "wait", "pods", "-l",
                            ",".join(f"{key}={value}" for key, value in cluster.label.items()),
                            "--for=condition=Ready", "--timeout=60s"), limit=65)
    return {endpoint: cluster.pod_ip(endpoint) for endpoint in sorted(ports)}


def policies(cluster: Cluster, matrix: dict, endpoints: Iterable[str], removed: str | None) -> list[dict]:
    labels = "rezono-network-endpoint"
    policies = []
    for endpoint in endpoints:
        grants = [case for case in matrix["cases"] if case["destination"] == endpoint
                  and case["service"] == "allow" and case["id"] != removed]
        rules = [
            {"from": [{"ipBlock": {"cidr": f'{IPv4Address(matrix["endpoints"][case["source"]]["address"])}/32'}}],
             "ports": [{"protocol": case["protocol"], "port": case["port"]}]}
            for case in grants
        ]
        name = f"{endpoint}-fixture-service"
        cluster.apply({
            "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": name, "namespace": NAMESPACE, "labels": cluster.label},
            "spec": {"podSelector": {"matchLabels": {labels: endpoint}}, "policyTypes": ["Ingress"],
                     "ingress": rules},
        })
        policies.append(cluster.read("get", "networkpolicy", name, namespace=NAMESPACE))
    return policies


def policy_observation(matrix: dict, documents: list[dict]) -> dict:
    allowed = []
    for document in documents:
        spec = document["spec"]
        endpoint = spec["podSelector"]["matchLabels"]["rezono-network-endpoint"]
        for case in matrix["cases"]:
            if case["destination"] != endpoint:
                continue
            cidr = f'{IPv4Address(matrix["endpoints"][case["source"]]["address"])}/32'
            if any({"ipBlock": {"cidr": cidr}} in rule["from"]
                   and {"protocol": case["protocol"], "port": case["port"]} in rule["ports"]
                   for rule in spec.get("ingress", [])):
                allowed.append(case["id"])
    changed, = (policy for policy in documents
                if policy["spec"]["podSelector"]["matchLabels"]["rezono-network-endpoint"] == "echo")
    metadata = changed["metadata"]
    if type(metadata.get("generation")) is not int or metadata["generation"] <= 0:
        raise RuntimeError("The observed echo NetworkPolicy has no API generation")
    return {"uid": metadata["uid"], "generation": metadata["generation"], "allowed": sorted(allowed),
            "resourceVersions": [policy["metadata"]["resourceVersion"] for policy in documents]}


def connected(command: list[str]) -> tuple[bool, int]:
    result = subprocess.run(command, text=True, capture_output=True, timeout=12)
    status = result.stdout.strip()
    if result.returncode != 0 or status not in {"0", "1", "124"}:
        raise RuntimeError(f"Socket probe failed without an observation: {result.stderr.strip()}")
    return status == "0", int(status)


def pod_probe(cluster: Cluster, name: str, addr: str, port: int) -> tuple[bool, int]:
    return connected(cluster.namespaced(NAMESPACE, "exec", name, "--", "/network-probe", "probe", addr, str(port)))


def event(cluster: Cluster, phase: str, kind: str, tick: int, **fields) -> dict:
    seconds, nanos = divmod(tick, 10**9)
    stamp = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    payload = {"run": cluster.run, "attempt": cluster.attempt, "feature": "network", "phase": phase,
               "collector": cluster.node, "window": f"{cluster.job}-{phase}", "kind": kind,
               "tick": tick, "observed_at": f"{stamp}.{nanos:09d}Z", **fields}
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {**payload, "evidence": f"sha256:{identity}"}


def sweep(cluster: Cluster, router: Router, hubble: Hubble, matrix: dict, targets: dict[str, str],
          phase: str, documents: list[dict], probe: Path) -> list[dict]:
    policy_tick = time_ns()
    result = [event(cluster, phase, "policy", policy_tick, **policy_observation(matrix, documents))]
    before = hubble.heartbeat(targets["echo"], targets["peer"], MARKER_PORT, policy_tick,
                              lambda: pod_probe(cluster, "echo", targets["peer"], MARKER_PORT))
    start = time_ns()
    destinations = {}
    for case in matrix["cases"]:
        source, destination, port = case["source"], case["destination"], case["port"]
        pair = {key: case[key] for key in ("id", "source", "destination", "protocol", "port")}
        source_ip = targets.get(source) or str(IPv4Address(matrix["endpoints"][source]["address"]))
        if source in router.clients:
            addr = str(IPv4Address(matrix["endpoints"][destination]["address"]))
            counters = router.counters()
            answered, status = connected(
                ["sudo", "-n", "ip", "netns", "exec", router.clients[source], str(probe), "probe", addr, str(port)]
            )
            verdict, rule, prior, current = router.verdict(counters)
            result.append(event(cluster, phase, "router", time_ns(), **pair, outcome=verdict,
                                nft_rule=rule, packets_before=prior, packets_after=current))
        else:
            answered, status = pod_probe(cluster, source, targets[destination], port)
        result.append(event(cluster, phase, "probe", time_ns(), **pair,
                            outcome="allow" if answered else "deny", status=status))
        destinations[(source_ip, targets[destination], port)] = pair
    stop = time_ns()
    after = hubble.heartbeat(targets["echo"], targets["peer"], MARKER_PORT, stop,
                             lambda: pod_probe(cluster, "echo", targets["peer"], MARKER_PORT))
    hubble.drain()
    for address, pair in destinations.items():
        matches = [flow for flow in hubble.flows if (flow.source, flow.destination, flow.port) == address
                   and start <= flow.tick < stop]
        observed = {flow.outcome for flow in matches}
        if len(observed) > 1:
            raise RuntimeError(f"Conflicting destination-side Hubble outcomes for {pair['id']}")
        if matches:
            first = min(matches, key=lambda flow: flow.tick)
            fingerprints = [hashlib.sha256(json.dumps(flow.event, sort_keys=True).encode()).hexdigest()
                            for flow in matches]
            result.append(event(cluster, phase, "hubble", first.tick, **pair, node=cluster.node,
                                outcome=first.outcome, flows=sorted(fingerprints)))
    return [
        event(cluster, phase, "window", start, start=start, stop=stop),
        event(cluster, phase, "node", after.tick, node=cluster.node, first=before.tick, last=after.tick,
              gaps=0, lost=0, bracket=[before.event, after.event]),
        *result,
    ]


def build_probe(cluster: Cluster, directory: Path) -> Path:
    probe = directory / "network-probe"
    env = {**os.environ, "CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": "amd64",
           "GOTOOLCHAIN": "local", "GO111MODULE": "off"}
    print(run("go", "version", env=env).strip(), flush=True)
    run("go", "build", "-trimpath", "-buildvcs=false", "-ldflags=-buildid=", "-o", str(probe),
        str(ROOT / "loop/cluster/network_probe.go"), limit=110, env=env)
    (directory / "Dockerfile").write_text(
        "FROM scratch\nCOPY network-probe /network-probe\nUSER 65534:65534\n", encoding="utf-8",
    )
    run("docker", "build", "--network=none", "--tag", cluster.image, str(directory), limit=80)
    try:
        run("kind", "load", "docker-image", cluster.image, "--name", "rezono-fixture", limit=90)
    finally:
        run("docker", "image", "rm", "--no-prune", cluster.image)
    return probe


def report_workloads(cluster: Cluster) -> None:
    for pod in cluster.read("get", "pods", namespace=NAMESPACE)["items"]:
        name = pod["metadata"]["name"]
        status = pod["status"]
        print(f"Fixture pod {name}: {json.dumps(status, sort_keys=True)}", flush=True)
        result = subprocess.run(cluster.namespaced(NAMESPACE, "logs", name), capture_output=True,
                                text=True, timeout=20)
        if result.stdout:
            print(result.stdout, flush=True)


def main() -> None:
    matrix = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cluster = Cluster(os.environ)
    prefix = f"rznet-{cluster.run}-{cluster.attempt}"
    cluster.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}})
    with TemporaryDirectory(prefix="rezono-network-") as directory:
        probe = build_probe(cluster, Path(directory))
        try:
            targets = start_services(cluster, matrix)
            with transit(prefix, cluster.node, matrix, targets, cluster.node_pid) as router, cluster.hubble() as hubble:
                records = []
                for phase, removed in (("baseline", None), ("changed", "echo")):
                    readback = policies(cluster, matrix, targets, removed)
                    sleep(3)
                    records.extend(sweep(cluster, router, hubble, matrix, targets, phase, readback, probe))
            cluster.record(records)
            print(f"Recorded {len(records)} actual observations in {cluster.job}")
        except Exception:
            report_workloads(cluster)
            raise
        finally:
            cluster.clean_workloads()


if __name__ == "__main__":
    main()
