"""Record a live RBAC membership-withdrawal trial on the disposable cluster."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
from time import monotonic, sleep
from typing import Any
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from examples.rules_support import State  # noqa: E402
from management_recorder import CONTEXT, ManagementCluster, run  # noqa: E402
from rezono_canon import canonical_sha256  # noqa: E402
from rezono_checker.check import check  # noqa: E402
from rezono_checker.rules import load_rules  # noqa: E402
from rezono_compiler import calc, facts, pack, rules  # noqa: E402

FEATURE = "access"
TENANT_NS = "elm"
PEER_NS = "reed"
TENANT_CLUSTER = "elm-app"
PEER_CLUSTER = "reed-app"
SERVICE_ACCOUNT = "reader"
MARKER_NAME = "public-marker"
MARKER_RESOURCE = f"configmaps/{MARKER_NAME}"
ROLE_NAME = "elm-reader"
BINDING_NAME = "elm-reader-binding"
SCOPE_LABEL = "rezono.org/managed-scope"
SCOPE_VALUE = "elm-access"
PUBLICATION_ANNOTATION = "rezono.org/publication-sha256"
TENANT_CONTEXT = "kind-rezono-fixture-tenant"
TENANT_KUBECONFIG_NAME = "rezono-fixture-tenant.kubeconfig"
BEFORE_DAY = "2026-06-09"
EXPIRY_DAY = "2026-06-10"
TOKEN_TTL_SECONDS = 3600


def access_records(identity: str, day: str) -> dict[str, list[dict[str, str]]]:
    """Build management access input facts for `identity` at evaluation `day`."""
    return {
        "cluster_membership": [
            {
                "id": "elm-lease",
                "identity": identity,
                "organization": TENANT_NS,
                "begins": "2026-06-01",
                "ends": EXPIRY_DAY,
            },
            {
                "id": "reed-lease",
                "identity": "peer",
                "organization": PEER_NS,
                "begins": "2026-06-01",
                "ends": "2026-06-30",
            },
        ],
        "cluster_action_decision": [
            {
                "id": "elm-read",
                "organization": TENANT_NS,
                "tenant_role": "reader",
                "cluster": TENANT_CLUSTER,
                "action": "get",
                "resource": "configmaps",
                "namespace": TENANT_NS,
            },
            {
                "id": "reed-read",
                "organization": PEER_NS,
                "tenant_role": "reader",
                "cluster": PEER_CLUSTER,
                "action": "get",
                "resource": "configmaps",
                "namespace": PEER_NS,
            },
        ],
        "cluster_tenant_role": [
            {
                "id": "role-elm",
                "identity": identity,
                "organization": TENANT_NS,
                "tenant_role": "reader",
            },
            {
                "id": "role-reed",
                "identity": "peer",
                "organization": PEER_NS,
                "tenant_role": "reader",
            },
        ],
        "cluster_emergency_grant": [],
        "cluster_right_clock": [{"id": "evaluation", "day": day}],
    }


def evaluate_state(model: Any, program: Any, calculation: Any, identity: str, day: str, label: str) -> State:
    """Compile and evaluate `management_access.dl` for `identity` on `day`."""
    rows = facts.rows_of(model, access_records(identity, day))
    return State(model, program, label, rows, calculation)


def verified_publication(model: Any, state: State, right: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    """Verify the proof of `right` and return `(publication_sha256, witness_summary)`."""
    proof = state.proof("managed_cluster_right", right)
    manifest, read = state.manifest()
    report = check(proof, manifest, load_rules(model.rules), read)
    if not report["valid"] or report["findings"]:
        raise RuntimeError(f"Access publication proof failed checker validation: {report['findings']}")
    leaves = {
        (premise["row"]["relation"], tuple(json.loads(premise["row"]["key"])))
        for witness in proof["witnesses"]
        for premise in witness["premises"]
        if premise["row"]["relation"] not in state.derived
    }
    if not any(rel.startswith("cluster_membership__") and key[0] == "elm-lease" for rel, key in leaves):
        raise RuntimeError("Access right proof does not cite elm-lease membership")
    witness_summary = {
        "proof_sha256": canonical_sha256(proof),
        "root": proof["root"],
        "witnesses": proof["witnesses"],
    }
    return canonical_sha256(manifest), witness_summary


def ensure_fixture_objects(cluster: ManagementCluster) -> None:
    """Create the tenant/peer namespaces, harmless ConfigMap markers, and reader ServiceAccount."""
    cluster.ensure_namespace(TENANT_NS)
    cluster.ensure_namespace(PEER_NS)
    for namespace, label in ((TENANT_NS, "elm-public"), (PEER_NS, "reed-public")):
        cluster.apply({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": MARKER_NAME, "namespace": namespace},
            "data": {"marker": label},
        })
    cluster.apply({
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": SERVICE_ACCOUNT, "namespace": TENANT_NS},
        "automountServiceAccountToken": False,
    })
    cluster.delete("rolebinding,role", "-l", f"{SCOPE_LABEL}={SCOPE_VALUE}", namespace=TENANT_NS)


def cluster_tls(cluster: ManagementCluster) -> tuple[str, str]:
    """Read the fixture API server URL and base64 CA bundle from the admin kubeconfig."""
    view = json.loads(
        run(
            "kubectl",
            "--kubeconfig",
            str(cluster.kubeconfig),
            "--context",
            CONTEXT,
            "config",
            "view",
            "--minify",
            "--raw",
            "-o",
            "json",
        )
    )
    cluster_cfg = view["clusters"][0]["cluster"]
    server = cluster_cfg["server"]
    if "certificate-authority-data" in cluster_cfg:
        ca_b64 = cluster_cfg["certificate-authority-data"]
    elif "certificate-authority" in cluster_cfg:
        ca_b64 = base64.b64encode(Path(cluster_cfg["certificate-authority"]).read_bytes()).decode("ascii")
    else:
        raise RuntimeError("Fixture kubeconfig lacks cluster certificate authority data")
    return server, ca_b64


def issue_tenant_credential(cluster: ManagementCluster, server: str, ca_b64: str) -> tuple[str, str, str, Path]:
    """Issue a ServiceAccount TokenRequest and write the dedicated tenant kubeconfig."""
    token_request = {
        "apiVersion": "authentication.k8s.io/v1",
        "kind": "TokenRequest",
        "spec": {"expirationSeconds": TOKEN_TTL_SECONDS},
    }
    response = json.loads(
        run(
            *cluster.command,
            "create",
            "--raw",
            f"/api/v1/namespaces/{TENANT_NS}/serviceaccounts/{SERVICE_ACCOUNT}/token",
            "-f",
            "-",
            data=json.dumps(token_request),
        )
    )
    status = response["status"]
    token = status["token"]
    expires_at = status["expirationTimestamp"]
    credential_ref = f"sha256:{hashlib.sha256(token.encode('utf-8')).hexdigest()}"

    kubeconfig_path = cluster.temp / TENANT_KUBECONFIG_NAME
    tenant_config = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": TENANT_CONTEXT,
        "clusters": [{
            "name": TENANT_CONTEXT,
            "cluster": {
                "server": server,
                "certificate-authority-data": ca_b64,
            },
        }],
        "contexts": [{
            "name": TENANT_CONTEXT,
            "context": {
                "cluster": TENANT_CONTEXT,
                "user": "elm-reader",
                "namespace": TENANT_NS,
            },
        }],
        "users": [{
            "name": "elm-reader",
            "user": {"token": token},
        }],
    }
    fd = os.open(kubeconfig_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(tenant_config, handle, indent=2)
        handle.write("\n")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with Path(github_env).open("a", encoding="utf-8") as env_file:
            env_file.write(f"REZONO_TENANT_TEST_KUBECONFIG={kubeconfig_path}\n")

    return token, credential_ref, expires_at, kubeconfig_path


def whoami(kubeconfig: Path) -> str:
    """Authenticate against the API server with `kubeconfig` and return the observed username."""
    info = json.loads(
        run(
            "kubectl",
            "--kubeconfig",
            str(kubeconfig),
            "--request-timeout=15s",
            "auth",
            "whoami",
            "-o",
            "json",
        )
    )
    return info["status"]["userInfo"]["username"]


def api_get_marker(
    server: str,
    ca_pem: str,
    token: str,
    namespace: str,
    expected_status: int,
) -> tuple[int, str]:
    """Perform a real HTTPS GET on `configmaps/public-marker` using the tenant bearer token."""
    url = f"{server.rstrip('/')}/api/v1/namespaces/{namespace}/{MARKER_RESOURCE}"
    context = ssl.create_default_context(cadata=ca_pem)
    deadline = monotonic() + 5.0
    last_status = 0
    last_reason = ""
    while True:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, context=context, timeout=15) as response:
                body = json.loads(response.read().decode("utf-8"))
                last_status = int(response.status)
                last_reason = str(response.reason or "OK")
                if last_status == expected_status:
                    if body.get("kind") != "ConfigMap" or body.get("metadata", {}).get("name") != MARKER_NAME:
                        raise RuntimeError(f"Unexpected ConfigMap read response in {namespace}")
                    return last_status, last_reason
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            body = json.loads(raw) if raw.strip().startswith("{") else {}
            last_status = int(err.code)
            last_reason = str(body.get("reason") or err.reason or "Error")
            if last_status == expected_status:
                return last_status, last_reason
        if monotonic() >= deadline:
            raise RuntimeError(
                f"Expected HTTP {expected_status} for {namespace}/{MARKER_RESOURCE}, got {last_status} ({last_reason})"
            )
        sleep(0.25)


def apply_rbac(cluster: ManagementCluster, publication_sha256: str) -> str:
    """Apply the derived Role and RoleBinding in `elm` and return the binding UID from readback."""
    metadata_common = {
        "namespace": TENANT_NS,
        "labels": {SCOPE_LABEL: SCOPE_VALUE},
        "annotations": {PUBLICATION_ANNOTATION: publication_sha256},
    }
    cluster.apply({
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": {"name": ROLE_NAME, **metadata_common},
        "rules": [{
            "apiGroups": [""],
            "resources": ["configmaps"],
            "resourceNames": [MARKER_NAME],
            "verbs": ["get"],
        }],
    })
    cluster.apply({
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": BINDING_NAME, **metadata_common},
        "subjects": [{
            "kind": "ServiceAccount",
            "name": SERVICE_ACCOUNT,
            "namespace": TENANT_NS,
        }],
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": ROLE_NAME,
        },
    })
    readback = cluster.read("get", "rolebinding", BINDING_NAME, namespace=TENANT_NS)
    annotations = readback.get("metadata", {}).get("annotations", {})
    if annotations.get(PUBLICATION_ANNOTATION) != publication_sha256:
        raise RuntimeError("RoleBinding readback is missing the expected publication digest annotation")
    return readback["metadata"]["uid"]


def remove_rbac_and_confirm_absence(cluster: ManagementCluster) -> bool:
    """Delete the managed RoleBinding/Role in `elm` and confirm complete absence under scope."""
    cluster.delete("rolebinding,role", "-l", f"{SCOPE_LABEL}={SCOPE_VALUE}", namespace=TENANT_NS)
    listing = cluster.read("get", "rolebindings", "-l", f"{SCOPE_LABEL}={SCOPE_VALUE}", namespace=TENANT_NS)
    if listing.get("items"):
        raise RuntimeError(f"Expected no RoleBindings remaining under {SCOPE_VALUE}, found {len(listing['items'])}")
    return listing.get("metadata", {}).get("remainingItemCount") is None


def main() -> None:
    cluster = ManagementCluster(os.environ)
    ensure_fixture_objects(cluster)
    server, ca_b64 = cluster_tls(cluster)
    ca_pem = base64.b64decode(ca_b64).decode("ascii")
    token, credential_ref, expires_at, tenant_kubeconfig = issue_tenant_credential(cluster, server, ca_b64)

    identity = whoami(tenant_kubeconfig)
    expected_identity = f"system:serviceaccount:{TENANT_NS}:{SERVICE_ACCOUNT}"
    if identity != expected_identity:
        raise RuntimeError(f"Expected tenant identity {expected_identity}, got {identity}")

    model = pack.read(ROOT / "examples" / "platform")
    program = rules.load(model.rules)
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None

    before_state = evaluate_state(model, program, calculation, identity, BEFORE_DAY, "before")
    elm_right = (identity, TENANT_CLUSTER, "get", "configmaps", TENANT_NS)
    reed_right = ("peer", PEER_CLUSTER, "get", "configmaps", PEER_NS)
    if before_state.derived.get("managed_cluster_right") != {elm_right, reed_right}:
        raise RuntimeError(f"Unexpected derived rights before expiry: {before_state.derived.get('managed_cluster_right')}")

    publication_sha256, witness_summary = verified_publication(model, before_state, elm_right)
    binding_uid = apply_rbac(cluster, publication_sha256)

    events: list[dict[str, Any]] = []
    events.append(
        cluster.make_event(
            FEATURE,
            "binding-applied",
            binding_name=BINDING_NAME,
            binding_uid=binding_uid,
            publication_sha256=publication_sha256,
            identity=identity,
            cluster=TENANT_CLUSTER,
            namespace=TENANT_NS,
            resource=MARKER_RESOURCE,
            verb="get",
            managed_scope=SCOPE_VALUE,
        )
    )

    before_status, before_reason = api_get_marker(server, ca_pem, token, TENANT_NS, 200)
    events.append(
        cluster.make_event(
            FEATURE,
            "same-credential-read",
            status=before_status,
            reason=before_reason,
            identity=identity,
            credential_ref=credential_ref,
            expires_at=expires_at,
            cluster=TENANT_CLUSTER,
            namespace=TENANT_NS,
            resource=MARKER_RESOURCE,
            verb="get",
        )
    )

    cross_status, cross_reason = api_get_marker(server, ca_pem, token, PEER_NS, 403)
    events.append(
        cluster.make_event(
            FEATURE,
            "other-tenant-read",
            status=cross_status,
            reason=cross_reason,
            identity=identity,
            credential_ref=credential_ref,
            expires_at=expires_at,
            cluster=PEER_CLUSTER,
            namespace=PEER_NS,
            resource=MARKER_RESOURCE,
            verb="get",
        )
    )

    after_state = evaluate_state(model, program, calculation, identity, EXPIRY_DAY, "after")
    if after_state.derived.get("managed_cluster_right") != {reed_right}:
        raise RuntimeError(f"Unexpected derived rights after expiry: {after_state.derived.get('managed_cluster_right')}")

    events.append(
        cluster.make_event(
            FEATURE,
            "right-withdrawn",
            weight=-1,
            membership="elm-lease",
            source_manifest=publication_sha256,
            previous_right_witness=witness_summary,
            identity=identity,
            cluster=TENANT_CLUSTER,
            namespace=TENANT_NS,
            resource=MARKER_RESOURCE,
            verb="get",
        )
    )

    complete = remove_rbac_and_confirm_absence(cluster)
    events.append(
        cluster.make_event(
            FEATURE,
            "binding-read-absent",
            previous_binding_uid=binding_uid,
            complete=complete,
            managed_scope=SCOPE_VALUE,
            cluster=TENANT_CLUSTER,
            namespace=TENANT_NS,
        )
    )

    denied_status, denied_reason = api_get_marker(server, ca_pem, token, TENANT_NS, 403)
    if whoami(tenant_kubeconfig) != identity:
        raise RuntimeError("Tenant credential stopped authenticating after membership withdrawal")

    events.append(
        cluster.make_event(
            FEATURE,
            "same-credential-read",
            status=denied_status,
            reason=denied_reason,
            identity=identity,
            credential_ref=credential_ref,
            expires_at=expires_at,
            cluster=TENANT_CLUSTER,
            namespace=TENANT_NS,
            resource=MARKER_RESOURCE,
            verb="get",
        )
    )

    cluster.record_job(FEATURE, events)


if __name__ == "__main__":
    main()
