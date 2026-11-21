"""Record a live RBAC membership-withdrawal trial on the disposable cluster."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
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
for _path in (ROOT, ROOT / "examples", ROOT / "examples" / "platform" / "proof_cases"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from examples.rules_support import State  # noqa: E402
from management_probes import compiled as compile_management_state  # noqa: E402
from management_recorder import CONTEXT, ManagementCluster, run  # noqa: E402
from rezono_canon import canonical_sha256  # noqa: E402
from rezono_checker import difference as checker_difference  # noqa: E402
from rezono_checker.check import check  # noqa: E402
from rezono_checker.rules import load_rules  # noqa: E402
from rezono_publisher import difference  # noqa: E402

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
TOKEN_TTL_SECONDS = 3600


def _access_dates() -> tuple[str, str, str, str]:
    """Return ISO calendar dates `(before_day, expiry_day, begins_day, peer_ends_day)` relative to UTC today."""
    before_date = datetime.now(timezone.utc).date()
    return (
        before_date.isoformat(),
        (before_date + timedelta(days=1)).isoformat(),
        (before_date - timedelta(days=8)).isoformat(),
        (before_date + timedelta(days=21)).isoformat(),
    )


def access_records(
    identity: str,
    day: str,
    *,
    begins_day: str | None = None,
    expiry_day: str | None = None,
    peer_ends_day: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Build management access input facts for `identity` at evaluation `day`."""
    if begins_day is None or expiry_day is None or peer_ends_day is None:
        _, default_expiry, default_begins, default_peer_ends = _access_dates()
        begins_day = begins_day or default_begins
        expiry_day = expiry_day or default_expiry
        peer_ends_day = peer_ends_day or default_peer_ends
    return {
        "cluster_membership": [
            {
                "id": "elm-lease",
                "identity": identity,
                "organization": TENANT_NS,
                "begins": begins_day,
                "ends": expiry_day,
            },
            {
                "id": "reed-lease",
                "identity": "peer",
                "organization": PEER_NS,
                "begins": begins_day,
                "ends": peer_ends_day,
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


def evaluate_state(
    identity: str,
    day: str,
    *,
    begins_day: str | None = None,
    expiry_day: str | None = None,
    peer_ends_day: str | None = None,
) -> tuple[Any, State]:
    """Compile and evaluate `management_access.dl` for `identity` on `day`."""
    return compile_management_state(
        access_records(
            identity,
            day,
            begins_day=begins_day,
            expiry_day=expiry_day,
            peer_ends_day=peer_ends_day,
        )
    )


def verified_publication(model: Any, state: State, right: tuple[str, ...]) -> tuple[str, dict[str, Any], str]:
    """Verify the proof of `right` and return `(publication_sha256, witness_summary, membership_id)`."""
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
    memberships = sorted(key[0] for rel, key in leaves if rel.startswith("cluster_membership__"))
    if not memberships:
        raise RuntimeError("Access right proof does not cite a cluster_membership")
    witness_summary = {
        "proof_sha256": canonical_sha256(proof),
        "root": proof["root"],
        "witnesses": proof["witnesses"],
    }
    return canonical_sha256(manifest), witness_summary, memberships[0]


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


def apply_rbac(
    cluster: ManagementCluster,
    publication_sha256: str,
    rights: list[tuple[str, ...]],
) -> str:
    """Apply the derived Role and RoleBinding in `elm` and return the binding UID from readback."""
    if not rights:
        raise RuntimeError("Cannot render Role without derived managed_cluster_right rows")
    namespace = rights[0][4]
    metadata_common = {
        "namespace": namespace,
        "labels": {SCOPE_LABEL: SCOPE_VALUE},
        "annotations": {PUBLICATION_ANNOTATION: publication_sha256},
    }
    cluster.apply({
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": {"name": ROLE_NAME, **metadata_common},
        "rules": [
            {
                "apiGroups": [""],
                "resources": [resource],
                "resourceNames": [MARKER_NAME],
                "verbs": [action],
            }
            for _, _, action, resource, _ in rights
        ],
    })
    cluster.apply({
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": BINDING_NAME, **metadata_common},
        "subjects": [{
            "kind": "ServiceAccount",
            "name": SERVICE_ACCOUNT,
            "namespace": namespace,
        }],
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": ROLE_NAME,
        },
    })
    readback = cluster.read("get", "rolebinding", BINDING_NAME, namespace=namespace)
    annotations = readback.get("metadata", {}).get("annotations", {})
    if annotations.get(PUBLICATION_ANNOTATION) != publication_sha256:
        raise RuntimeError("RoleBinding readback is missing the expected publication digest annotation")
    return readback["metadata"]["uid"]


def remove_rbac_and_confirm_absence(cluster: ManagementCluster, namespace: str = TENANT_NS) -> bool:
    """Delete the managed RoleBinding/Role in `elm` and confirm complete absence under scope."""
    cluster.delete("rolebinding,role", "-l", f"{SCOPE_LABEL}={SCOPE_VALUE}", namespace=namespace)
    complete = True
    for resource_kind, label in (("rolebindings", "RoleBindings"), ("roles", "Roles")):
        listing = cluster.read("get", resource_kind, "-l", f"{SCOPE_LABEL}={SCOPE_VALUE}", namespace=namespace)
        if listing.get("items"):
            raise RuntimeError(f"Expected no {label} remaining under {SCOPE_VALUE}, found {len(listing['items'])}")
        if listing.get("metadata", {}).get("remainingItemCount") is not None:
            complete = False
    return complete


def _withdrawn_right_deltas(
    before_state: State,
    after_state: State,
    identity: str,
    cluster_name: str,
    namespace: str,
) -> list[tuple[tuple[str, ...], int]]:
    """Derive withdrawn `(right_key, weight)` pairs for `identity` from publication snapshots."""
    before_bytes = before_state.explainer.snapshot("managed_cluster_right").encode("utf-8")
    after_bytes = after_state.explainer.snapshot("managed_cluster_right").encode("utf-8")
    entries = difference.entries(before_bytes, after_bytes)
    if entries != checker_difference.changes(before_bytes, after_bytes):
        raise RuntimeError("Publication difference disagreement between publisher and checker")
    deltas: list[tuple[tuple[str, ...], int]] = []
    for entry in entries:
        change = entry["change"]
        if change == "removed":
            deltas.append((tuple(entry["key"]), -1))
        elif change == "changed":
            deltas.append((tuple(entry["was"]), -1))
            deltas.append((tuple(entry["key"]), 1))
        elif change == "added":
            deltas.append((tuple(entry["key"]), 1))
        else:
            raise RuntimeError(f"Unsupported publication difference change: {change!r}")
    return [
        (key, weight)
        for key, weight in deltas
        if weight < 0 and key[0] == identity and key[1] == cluster_name and key[4] == namespace
    ]


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

    before_day, expiry_day, begins_day, peer_ends_day = _access_dates()
    model, before_state = evaluate_state(
        identity,
        before_day,
        begins_day=begins_day,
        expiry_day=expiry_day,
        peer_ends_day=peer_ends_day,
    )
    before_rights = before_state.derived.get("managed_cluster_right", set())
    tenant_rights = sorted(
        row for row in before_rights if row[0] == identity and row[1] == TENANT_CLUSTER and row[4] == TENANT_NS
    )
    if not tenant_rights:
        raise RuntimeError(f"No derived managed_cluster_right for {identity} before expiry: {before_rights}")

    primary_right = tenant_rights[0]
    _, target_cluster, action, resource, target_namespace = primary_right
    marker_resource = f"{resource}/{MARKER_NAME}"

    publication_sha256, witness_summary, membership_id = verified_publication(model, before_state, primary_right)
    binding_uid = apply_rbac(cluster, publication_sha256, tenant_rights)

    events: list[dict[str, Any]] = []
    events.append(
        cluster.make_event(
            FEATURE,
            "binding-applied",
            binding_name=BINDING_NAME,
            binding_uid=binding_uid,
            publication_sha256=publication_sha256,
            identity=identity,
            cluster=target_cluster,
            namespace=target_namespace,
            resource=marker_resource,
            verb=action,
            managed_scope=SCOPE_VALUE,
        )
    )

    before_status, before_reason = api_get_marker(server, ca_pem, token, target_namespace, 200)
    events.append(
        cluster.make_event(
            FEATURE,
            "same-credential-read",
            status=before_status,
            reason=before_reason,
            identity=identity,
            credential_ref=credential_ref,
            expires_at=expires_at,
            cluster=target_cluster,
            namespace=target_namespace,
            resource=marker_resource,
            verb=action,
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
            resource=marker_resource,
            verb=action,
        )
    )

    _, after_state = evaluate_state(
        identity,
        expiry_day,
        begins_day=begins_day,
        expiry_day=expiry_day,
        peer_ends_day=peer_ends_day,
    )
    withdrawn = _withdrawn_right_deltas(before_state, after_state, identity, target_cluster, target_namespace)

    if withdrawn:
        for withdrawn_key, delta_weight in withdrawn:
            _, w_cluster, w_action, w_resource, w_namespace = withdrawn_key
            events.append(
                cluster.make_event(
                    FEATURE,
                    "right-withdrawn",
                    weight=delta_weight,
                    membership=membership_id,
                    source_manifest=publication_sha256,
                    previous_right_witness=witness_summary,
                    identity=identity,
                    cluster=w_cluster,
                    namespace=w_namespace,
                    resource=f"{w_resource}/{MARKER_NAME}",
                    verb=w_action,
                )
            )

        complete = remove_rbac_and_confirm_absence(cluster, namespace=target_namespace)
        events.append(
            cluster.make_event(
                FEATURE,
                "binding-read-absent",
                previous_binding_uid=binding_uid,
                complete=complete,
                managed_scope=SCOPE_VALUE,
                cluster=target_cluster,
                namespace=target_namespace,
            )
        )

        denied_status, denied_reason = api_get_marker(server, ca_pem, token, target_namespace, 403)
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
                cluster=target_cluster,
                namespace=target_namespace,
                resource=marker_resource,
                verb=action,
            )
        )

    cluster.record_job(FEATURE, events)


if __name__ == "__main__":
    main()
