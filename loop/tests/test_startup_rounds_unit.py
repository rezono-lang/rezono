"""Unit and counterexample tests for loop.startup_rounds readback and pack evaluation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Any

import pytest
import yaml

from loop.startup_rounds import (
    INVARIANTS,
    MANIFEST_ID,
    PLATFORM_FACTS,
    RUN_LABEL,
    SERVICE_LABEL,
    STARTUP_PROGRAM,
    NetworkCaseSpec,
    RoundStep,
    StartupCluster,
    StartupTopology,
    _namespace_name,
    _read_protected_endpoints,
    build_snapshot,
    certify_and_select_round,
    load_startup_topology,
)
from rezono_canon import canonical_sha256
from rezono_compiler import rules as compiler_rules
from rezono_compiler.facts import LoadError
from rezono_compiler.pack import CompileError
from rezono_publisher import store


def _policy(
    *,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    annotations: dict[str, str] | None = None,
    generation: int = 1,
    uid: str = "uid-1",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": name,
        "namespace": namespace,
        "generation": generation,
        "uid": uid,
    }
    if annotations is not None:
        meta["annotations"] = annotations
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": meta,
        "spec": spec,
    }


def _default_deny(namespace: str, *, ingress: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"podSelector": {}, "policyTypes": ["Ingress"]}
    if ingress is not None:
        spec["ingress"] = ingress
    return _policy(name="rezono-default-deny", namespace=namespace, spec=spec, uid=f"deny-{namespace}")


def _core_topology() -> StartupTopology:
    return StartupTopology(
        zones=("core", "app-core", "caller"),
        endpoints=(("api", "core", 8443), ("client", "caller", 8080)),
        endpoint_zones={"core/api": "core"},
        cases=(
            NetworkCaseSpec(
                case_id="client-to-api",
                source_service="client",
                source_zone="caller",
                destination_service="api",
                destination_zone="core",
                port=8443,
                expected="allow",
                function="identity",
            ),
        ),
        prohibited_recovery_flow={"source": "rec", "destination": "api", "function": "identity"},
        unsigned_artifact={"service": "lab", "artifact": "a-lab"},
    )


def test_read_protected_endpoints_rejects_suffix_collision_default_deny() -> None:
    from loop.startup_rounds import _expected_protections

    run = "r1"
    topo = _core_topology()
    expected = _expected_protections(run, topo)
    spec = expected["core/api"]

    # Default-deny exists ONLY in r1-app-core (suffix "-core"), NOT in r1-core.
    policies = [
        _default_deny(_namespace_name(run, "app-core")),
        _policy(
            name="rezono-protect-api",
            namespace=spec.namespace,
            annotations={"rezono.org/protected-endpoint": "core/api"},
            spec={
                "podSelector": spec.pod_selector,
                "policyTypes": ["Ingress"],
                "ingress": list(spec.ingress),
            },
            uid="protect-api",
        ),
    ]
    assert _read_protected_endpoints(policies, run, expected) == []


def test_read_protected_endpoints_rejects_wrong_namespace_for_protection_policy() -> None:
    from loop.startup_rounds import _expected_protections

    run = "r1"
    topo = _core_topology()
    expected = _expected_protections(run, topo)
    spec = expected["core/api"]

    policies = [
        _default_deny(spec.namespace),
        _policy(
            name="rezono-protect-api",
            namespace=_namespace_name(run, "app-core"),
            annotations={"rezono.org/protected-endpoint": "core/api"},
            spec={
                "podSelector": spec.pod_selector,
                "policyTypes": ["Ingress"],
                "ingress": list(spec.ingress),
            },
            uid="protect-wrong-ns",
        ),
    ]
    assert _read_protected_endpoints(policies, run, expected) == []


def test_read_protected_endpoints_rejects_loose_selector_and_wide_open_ingress() -> None:
    from loop.startup_rounds import _expected_protections

    run = "r1"
    topo = _core_topology()
    expected = _expected_protections(run, topo)
    spec = expected["core/api"]

    valid_protect = _policy(
        name="rezono-protect-api",
        namespace=spec.namespace,
        annotations={"rezono.org/protected-endpoint": "core/api"},
        spec={
            "podSelector": spec.pod_selector,
            "policyTypes": ["Ingress"],
            "ingress": list(spec.ingress),
        },
        uid="protect-valid",
    )

    # 1. Empty podSelector ({}) selects every pod in the namespace.
    bad_empty_selector = _policy(
        name="rezono-protect-api",
        namespace=spec.namespace,
        annotations={"rezono.org/protected-endpoint": "core/api"},
        spec={"podSelector": {}, "policyTypes": ["Ingress"], "ingress": list(spec.ingress)},
        uid="bad-empty-sel",
    )
    assert _read_protected_endpoints([_default_deny(spec.namespace), bad_empty_selector], run, expected) == []

    # 2. Wrong service label in podSelector.
    bad_wrong_service = _policy(
        name="rezono-protect-api",
        namespace=spec.namespace,
        annotations={"rezono.org/protected-endpoint": "core/api"},
        spec={
            "podSelector": {"matchLabels": {SERVICE_LABEL: "other"}},
            "policyTypes": ["Ingress"],
            "ingress": list(spec.ingress),
        },
        uid="bad-wrong-svc",
    )
    assert _read_protected_endpoints([_default_deny(spec.namespace), bad_wrong_service], run, expected) == []

    # 3. Wide-open ingress rule [{}].
    wide_open_ingress = _policy(
        name="rezono-protect-api",
        namespace=spec.namespace,
        annotations={"rezono.org/protected-endpoint": "core/api"},
        spec={"podSelector": spec.pod_selector, "policyTypes": ["Ingress"], "ingress": [{}]},
        uid="bad-wide-open",
    )
    assert _read_protected_endpoints([_default_deny(spec.namespace), wide_open_ingress], run, expected) == []

    # 4. Extra unexpected ingress rule added to expected rules.
    extra_rule = _policy(
        name="rezono-protect-api",
        namespace=spec.namespace,
        annotations={"rezono.org/protected-endpoint": "core/api"},
        spec={
            "podSelector": spec.pod_selector,
            "policyTypes": ["Ingress"],
            "ingress": [*spec.ingress, {"ports": [{"protocol": "TCP", "port": 9999}]}],
        },
        uid="bad-extra-rule",
    )
    assert _read_protected_endpoints([_default_deny(spec.namespace), extra_rule], run, expected) == []

    # 5. Default-deny policy itself has a wide-open ingress rule.
    assert _read_protected_endpoints([_default_deny(spec.namespace, ingress=[{}]), valid_protect], run, expected) == []

    # 6. Additional rogue namespace-wide allow-all NetworkPolicy alongside valid policies.
    rogue_ns_wide = _policy(
        name="rogue-allow-all",
        namespace=spec.namespace,
        spec={"podSelector": {}, "policyTypes": ["Ingress"], "ingress": [{}]},
        uid="rogue-ns",
    )
    assert _read_protected_endpoints([_default_deny(spec.namespace), valid_protect, rogue_ns_wide], run, expected) == []

    # 7. Additional rogue policy selecting the protected service with wide-open ingress.
    rogue_svc_open = _policy(
        name="rogue-open-api",
        namespace=spec.namespace,
        spec={"podSelector": spec.pod_selector, "policyTypes": ["Ingress"], "ingress": [{}]},
        uid="rogue-svc",
    )
    assert _read_protected_endpoints([_default_deny(spec.namespace), valid_protect, rogue_svc_open], run, expected) == []


def _multi_service_topology() -> StartupTopology:
    return StartupTopology(
        zones=("core", "caller"),
        endpoints=(("lb", "core", 443), ("api", "core", 8443), ("client", "caller", 8080)),
        endpoint_zones={"core/lb": "core", "core/api": "core"},
        cases=(
            NetworkCaseSpec(
                case_id="client-to-lb",
                source_service="client",
                source_zone="caller",
                destination_service="lb",
                destination_zone="core",
                port=443,
                expected="allow",
                function="ingress",
            ),
            NetworkCaseSpec(
                case_id="lb-to-api",
                source_service="lb",
                source_zone="core",
                destination_service="api",
                destination_zone="core",
                port=8443,
                expected="allow",
                function="identity",
            ),
        ),
        prohibited_recovery_flow={"source": "rec", "destination": "api", "function": "identity"},
        unsigned_artifact={"service": "lab", "artifact": "a-lab"},
    )


def _protect_policy(ep_id: str, spec: Any, *, uid: str | None = None) -> dict[str, Any]:
    policy_spec: dict[str, Any] = {
        "podSelector": spec.pod_selector,
        "policyTypes": ["Ingress"],
    }
    if spec.ingress:
        policy_spec["ingress"] = list(spec.ingress)
    return _policy(
        name=f"rezono-protect-{spec.service}",
        namespace=spec.namespace,
        annotations={"rezono.org/protected-endpoint": ep_id},
        spec=policy_spec,
        uid=uid or f"protect-{spec.service}",
    )


def test_read_protected_endpoints_rejects_omitted_policy_types_and_extra_selectors() -> None:
    from loop.startup_rounds import _expected_protections

    run = "run1"
    topo = _multi_service_topology()
    expected = _expected_protections(run, topo)
    lb_spec = expected["core/lb"]
    api_spec = expected["core/api"]
    base = [
        _default_deny(lb_spec.namespace),
        _protect_policy("core/lb", lb_spec),
        _protect_policy("core/api", api_spec),
    ]
    assert _read_protected_endpoints(base, run, expected) == ["core/api", "core/lb"]

    # 1. Extra policy with omitted policyTypes (defaults to Ingress in Kubernetes).
    omitted_policy_types = _policy(
        name="rogue-omitted-policy-types",
        namespace=lb_spec.namespace,
        spec={"podSelector": {}, "ingress": [{}]},
        uid="rogue-omitted-pt",
    )
    assert _read_protected_endpoints([*base, omitted_policy_types], run, expected) == []

    # 2. Extra policy with empty policyTypes list (also defaults to Ingress in Kubernetes).
    empty_policy_types = _policy(
        name="rogue-empty-policy-types",
        namespace=lb_spec.namespace,
        spec={"podSelector": {}, "policyTypes": [], "ingress": [{}]},
        uid="rogue-empty-pt",
    )
    assert _read_protected_endpoints([*base, empty_policy_types], run, expected) == []

    # 3. Extra policy selecting pods via rezono.org/run label.
    run_label_policy = _policy(
        name="rogue-run-label",
        namespace=lb_spec.namespace,
        spec={
            "podSelector": {"matchLabels": {RUN_LABEL: run}},
            "policyTypes": ["Ingress"],
            "ingress": [{}],
        },
        uid="rogue-run-label",
    )
    assert _read_protected_endpoints([*base, run_label_policy], run, expected) == []

    # 4. Extra policy selecting pods via combined matchLabels (service + run).
    combined_labels_policy = _policy(
        name="rogue-combined-labels",
        namespace=lb_spec.namespace,
        spec={
            "podSelector": {"matchLabels": {SERVICE_LABEL: "lb", RUN_LABEL: run}},
            "policyTypes": ["Ingress"],
            "ingress": [{}],
        },
        uid="rogue-combined",
    )
    assert _read_protected_endpoints([*base, combined_labels_policy], run, expected) == []

    # 5. Extra policy selecting pods via matchExpressions.
    match_expressions_policy = _policy(
        name="rogue-match-expressions",
        namespace=lb_spec.namespace,
        spec={
            "podSelector": {
                "matchExpressions": [
                    {"key": SERVICE_LABEL, "operator": "In", "values": ["lb"]},
                ],
            },
            "policyTypes": ["Ingress"],
            "ingress": [{}],
        },
        uid="rogue-expr",
    )
    assert _read_protected_endpoints([*base, match_expressions_policy], run, expected) == []

    # 6. Extra policy with malformed policyTypes fails closed.
    malformed_policy_types = _policy(
        name="rogue-malformed-pt",
        namespace=lb_spec.namespace,
        spec={"podSelector": {}, "policyTypes": "Egress", "ingress": [{}]},
        uid="rogue-malformed",
    )
    assert _read_protected_endpoints([*base, malformed_policy_types], run, expected) == []


def test_read_protected_endpoints_allows_multi_service_and_egress_only_policies() -> None:
    from loop.startup_rounds import _expected_protections

    run = "run1"
    topo = _multi_service_topology()
    expected = _expected_protections(run, topo)
    lb_spec = expected["core/lb"]
    api_spec = expected["core/api"]
    ns = lb_spec.namespace

    egress_only = _policy(
        name="allow-dns-egress",
        namespace=ns,
        spec={
            "podSelector": {},
            "policyTypes": ["Egress"],
            "egress": [{"ports": [{"protocol": "UDP", "port": 53}]}],
        },
        uid="egress-only",
    )

    policies = [
        _default_deny(ns),
        _protect_policy("core/lb", lb_spec),
        _protect_policy("core/api", api_spec),
        egress_only,
    ]
    assert _read_protected_endpoints(policies, run, expected) == ["core/api", "core/lb"]

    # An egress-only policy named rezono-default-deny cannot satisfy ingress default-deny.
    egress_default_deny = _policy(
        name="rezono-default-deny",
        namespace=ns,
        spec={"podSelector": {}, "policyTypes": ["Egress"]},
        uid="egress-deny",
    )
    assert (
        _read_protected_endpoints(
            [egress_default_deny, _protect_policy("core/lb", lb_spec), _protect_policy("core/api", api_spec)],
            run,
            expected,
        )
        == []
    )


def test_read_protected_endpoints_accepts_exact_policies_for_platform_topology() -> None:
    from loop.startup_rounds import _expected_protections

    run = "safe-start-42-1"
    topo = load_startup_topology()
    expected = _expected_protections(run, topo)

    policies: list[dict[str, Any]] = []
    for zone in topo.zones:
        policies.append(_default_deny(_namespace_name(run, zone)))

    for ep_id, spec in sorted(expected.items()):
        # Mirror Kubernetes API server omitting "ingress" when empty and reversing rule order when non-empty.
        policy_spec: dict[str, Any] = {
            "podSelector": spec.pod_selector,
            "policyTypes": ["Ingress"],
        }
        if spec.ingress:
            policy_spec["ingress"] = list(reversed(spec.ingress))
        policies.append(
            _policy(
                name=f"rezono-protect-{spec.service}",
                namespace=spec.namespace,
                annotations={"rezono.org/protected-endpoint": ep_id},
                spec=policy_spec,
                uid=f"protect-{spec.service}",
            )
        )

    assert _read_protected_endpoints(policies, run, expected) == sorted(expected)


def test_load_startup_topology_evaluates_platform_pack_and_rejects_unknown_signed(tmp_path: Path) -> None:
    topo = load_startup_topology()
    assert topo.prohibited_recovery_flow == {"source": "restore-bad", "destination": "idp", "function": "identity"}
    assert topo.unsigned_artifact == {"service": "lab", "artifact": "a-lab"}
    assert topo.zones == ("entry", "platform", "recovery", "tenant")
    assert set(topo.endpoint_zones) == {"entry/lb", "platform/idp"}
    assert [(c.case_id, c.expected) for c in topo.cases] == [
        ("lb-to-idp", "allow"),
        ("shop-to-idp", "allow"),
        ("restore-bad-to-idp", "deny"),
    ]

    # Counterexample 1: omitting `signed` on the unsigned artifact must NEVER be treated as "no".
    raw = yaml.safe_load(PLATFORM_FACTS.read_text(encoding="utf-8"))
    for art in raw["artifact"]:
        if art["id"] == "a-lab":
            art.pop("signed")
    missing_signed = tmp_path / "missing_signed.yaml"
    missing_signed.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises((CompileError, LoadError, RuntimeError, ValueError)):
        load_startup_topology(missing_signed)

    # Counterexample 2: even at the relation layer, missing artifact__signed (unknown) is never read as "no".
    from loop.startup_rounds import _select_topology_from_relations

    relations_with_unknown_signed = {
        "zone_of": {("lb", "entry"), ("idp", "platform"), ("shop", "tenant"), ("restore-bad", "recovery"), ("lab", "tenant")},
        "flow": {
            ("shop", "idp", "identity", "8443"),
            ("restore-bad", "idp", "identity", "8443"),
        },
        "provides": {("lb", "ingress", "443"), ("idp", "identity", "8443")},
        "recovery_reaches_out": {("restore-bad", "idp", "identity")},
        "unverified_supply": {("lab",), ("restore-bad",)},
        "verified": {("shop",)},
        "zone__entry_boundary": {("entry", "yes")},
        "zone__workload": {("tenant", "yes")},
        "artifact__for_service": {("a-shop", "shop"), ("a-lab", "lab")},
        "artifact__signed": {("a-shop", "yes")},  # a-lab signed is missing/unknown, NOT "no"
    }
    with pytest.raises(RuntimeError, match="explicitly unsigned"):
        _select_topology_from_relations(relations_with_unknown_signed)


def _platform_ports_and_transport_rows() -> dict[str, Any]:
    """Load the platform pack's port_decision and vendor_default_transport_source rows for standalone fixtures."""
    port_raw = yaml.safe_load((PLATFORM_FACTS.parent / "port_decision.yaml").read_text(encoding="utf-8"))
    transport_rows: list[dict[str, Any]] = []
    for path in sorted(PLATFORM_FACTS.parent.glob("*_transport_source.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        transport_rows.extend(doc.get("vendor_default_transport_source", []))
    return {
        "port_decision": port_raw["port_decision"],
        "vendor_default_transport_source": transport_rows,
    }


def test_load_startup_topology_does_not_merge_pack_signatures_into_external_facts(tmp_path: Path) -> None:
    # Default pack facts in examples/platform/facts/ still merge the sibling artifact_signature.yaml.
    default_topo = load_startup_topology()
    assert default_topo.unsigned_artifact == {"service": "lab", "artifact": "a-lab"}

    # An external custom facts file without signature rows must not silently inherit
    # pack_root/facts/artifact_signature.yaml (supplying port/transport rows isolates signature checking).
    raw = yaml.safe_load(PLATFORM_FACTS.read_text(encoding="utf-8"))
    assert "artifact_signature" not in raw and "signature_scan" not in raw
    base_with_transport = raw | _platform_ports_and_transport_rows()
    external_without_sigs = tmp_path / "custom_core.yaml"
    external_without_sigs.write_text(yaml.safe_dump(base_with_transport, sort_keys=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="unverified_supply|verified workload"):
        load_startup_topology(external_without_sigs)

    # When the external facts file provides its own signature evidence, evaluation succeeds.
    sig_raw = yaml.safe_load((PLATFORM_FACTS.parent / "artifact_signature.yaml").read_text(encoding="utf-8"))
    external_with_sigs = tmp_path / "custom_core_with_sigs.yaml"
    external_with_sigs.write_text(yaml.safe_dump(base_with_transport | sig_raw, sort_keys=False), encoding="utf-8")
    assert load_startup_topology(external_with_sigs) == default_topo


def test_load_startup_topology_does_not_merge_pack_ports_or_transport_into_external_facts(tmp_path: Path) -> None:
    # Counter-case: default pack facts still merge their own siblings under examples/platform/facts/.
    default_topo = load_startup_topology()
    assert default_topo.endpoints[0] == ("lb", "entry", 8443)
    assert default_topo.endpoints[1] == ("idp", "platform", 8443)

    core_raw = yaml.safe_load(PLATFORM_FACTS.read_text(encoding="utf-8"))
    sig_raw = yaml.safe_load((PLATFORM_FACTS.parent / "artifact_signature.yaml").read_text(encoding="utf-8"))
    core_with_sigs = core_raw | sig_raw
    assert "port_decision" not in core_with_sigs and "vendor_default_transport_source" not in core_with_sigs

    # 1. An external facts directory with neither port_decision.yaml nor *_transport_source.yaml must NOT
    #    silently inherit examples/platform/facts/*_transport_source.yaml (so idp has no derived flow/port).
    isolated_dir = tmp_path / "isolated"
    isolated_dir.mkdir()
    isolated_facts = isolated_dir / "custom_core.yaml"
    isolated_facts.write_text(yaml.safe_dump(core_with_sigs, sort_keys=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="prohibited recovery flow"):
        load_startup_topology(isolated_facts)

    # 2. An external facts directory providing its own sibling *_transport_source.yaml (port 9443 for keycloak)
    #    but NO port_decision.yaml must NOT silently inherit examples/platform/facts/port_decision.yaml
    #    (port 443 -> 8443 fallback); lb must fall back to the derived destination port 9443 instead.
    kc_raw = yaml.safe_load((PLATFORM_FACTS.parent / "keycloak_transport_source.yaml").read_text(encoding="utf-8"))
    kc_custom = {
        "vendor_default_transport_source": [
            {**row, "port": 9443} for row in kc_raw["vendor_default_transport_source"]
        ],
    }
    no_port_dir = tmp_path / "no_port_decision"
    no_port_dir.mkdir()
    no_port_facts = no_port_dir / "custom_core.yaml"
    no_port_facts.write_text(yaml.safe_dump(core_with_sigs, sort_keys=False), encoding="utf-8")
    (no_port_dir / "keycloak_transport_source.yaml").write_text(
        yaml.safe_dump(kc_custom, sort_keys=False), encoding="utf-8",
    )
    no_port_topo = load_startup_topology(no_port_facts)
    assert dict((svc, port) for svc, _, port in no_port_topo.endpoints)["idp"] == 9443
    assert dict((svc, port) for svc, _, port in no_port_topo.endpoints)["lb"] == 9443

    # 3. Counter-case: when the external facts directory provides its own sibling port_decision.yaml and
    #    *_transport_source.yaml, both siblings in tmp_path are read and reflected in the derived topology.
    port_raw = yaml.safe_load((PLATFORM_FACTS.parent / "port_decision.yaml").read_text(encoding="utf-8"))
    port_custom = {
        "port_decision": [
            ({**row, "port": 1443} if row["id"] == "pd-lb-ingress" else row)
            for row in port_raw["port_decision"]
        ],
    }
    own_dir = tmp_path / "own_siblings"
    own_dir.mkdir()
    own_facts = own_dir / "custom_core.yaml"
    own_facts.write_text(yaml.safe_dump(core_with_sigs, sort_keys=False), encoding="utf-8")
    (own_dir / "port_decision.yaml").write_text(yaml.safe_dump(port_custom, sort_keys=False), encoding="utf-8")
    (own_dir / "keycloak_transport_source.yaml").write_text(
        yaml.safe_dump(kc_custom, sort_keys=False), encoding="utf-8",
    )
    own_topo = load_startup_topology(own_facts)
    by_service = {svc: port for svc, _, port in own_topo.endpoints}
    assert by_service["lb"] == 1443
    assert by_service["idp"] == 9443
    assert all(case.port == 9443 for case in own_topo.cases)


def test_build_snapshot_uses_compiler_program_and_certifies_rounds() -> None:
    # STARTUP_PROGRAM must be a valid rezono.rules/1 IR loadable by rezono_compiler.rules.
    loaded = compiler_rules.load(STARTUP_PROGRAM, require_witness=False)
    assert set(INVARIANTS).issubset(loaded.derived())

    run = "safe-start-99-1"
    ep_ns = {"entry/lb": f"{run}-entry", "platform/idp": f"{run}-platform"}
    unsafe = build_snapshot(
        "unsafe-test",
        managed_namespaces=[f"{run}-entry"],
        protected_endpoints=["entry/lb"],
        exposed_endpoints=["entry/lb", "platform/idp"],
        endpoint_namespaces=ep_ns,
    )
    assert unsafe["rows"]["unprotected_exposure"] == [("platform/idp",)]
    assert unsafe["rows"]["exposed_without_namespace"] == [("platform/idp",)]
    assert {w["rule_id"] for w in unsafe["witnesses"]} == {
        "namespace_active",
        "unprotected_exposure",
        "exposed_without_namespace",
    }

    with TemporaryDirectory() as tmpdir:
        archive = store.FileStore(Path(tmpdir))
        protect_step = RoundStep(
            step_id="protect-endpoints",
            priority=0,
            plan_hash=canonical_sha256({"step": "protect"}),
            writes=frozenset({"ep-protect:entry/lb"}),
            delta=(("endpoint_protected", ("entry/lb",), 1),),
        )
        expose_step = RoundStep(
            step_id="expose-endpoints",
            priority=1,
            plan_hash=canonical_sha256({"step": "expose"}),
            writes=frozenset({"ep-expose:entry/lb"}),
            delta=(("endpoint_exposed", ("entry/lb",), 1),),
        )
        chosen, _, _ = certify_and_select_round(
            archive,
            run=run,
            cut="protected",
            event_time=2,
            base_namespaces={f"{run}-entry", f"{run}-platform"},
            base_protected=set(),
            base_exposed=set(),
            endpoint_namespaces=ep_ns,
            candidates=(protect_step, expose_step),
            width=2,
        )
        assert [step.step_id for step in chosen] == ["protect-endpoints"]
        assert STARTUP_PROGRAM["pack"] == MANIFEST_ID


def test_verify_unsigned_admission_denial_binds_to_derived_unsigned_artifact() -> None:
    from loop.startup_rounds import _unsigned_artifact_image

    pub_digest = "a" * 64
    unsigned = {"service": "lab", "artifact": "a-lab"}
    expected_image = _unsigned_artifact_image(unsigned)
    captured: list[dict[str, Any]] = []

    def fake_runner(
        args: list[str],
        *,
        data: str | None = None,
        timeout: int = 30,
        env: Any = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        subcommand = args[3:]
        if subcommand == ["-n", "argocd", "get", "applications.argoproj.io", "rezono-admission", "-o", "json"]:
            payload = {
                "status": {
                    "sync": {"status": "Synced"},
                    "resources": [{
                        "kind": "NamespacePublication",
                        "namespace": "admission-blue",
                        "name": "admission-sample",
                        "status": "Synced",
                    }],
                },
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if subcommand == [
            "-n",
            "admission-blue",
            "get",
            "namespacepublications.admission.rezono.org",
            "admission-sample",
            "-o",
            "json",
        ]:
            payload = {
                "spec": {
                    "digest": pub_digest,
                    "images": [{"service": "web", "image": "registry.example.org/sample/app@sha256:" + "1" * 64}],
                },
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if subcommand == ["create", "--dry-run=server", "-f", "-"]:
            assert data is not None
            pod = json.loads(data)
            captured.append(pod)
            err = (
                f'The pods "{pod["metadata"]["name"]}" is invalid: '
                f'ValidatingAdmissionPolicy \'verified-supply.{pub_digest[:32]}.{pub_digest[32:]}\' '
                f'denied request: verified-supply ({pub_digest}): image exceeds published verified supply'
            )
            return subprocess.CompletedProcess(args, 1, stdout="", stderr=err)
        raise AssertionError(f"unexpected command: {args}")

    cluster = object.__new__(StartupCluster)
    cluster.env = {}
    cluster.runner = fake_runner
    cluster.command = ["kubectl", "--context", "kind-rezono-fixture"]
    cluster.run = "safe-start-7-1"
    cluster._verify_admission_reconciled()

    outcome = cluster.verify_unsigned_admission_denial(unsigned)
    assert outcome == {
        "denied": True,
        "policy": "verified-supply",
        "namespace": "admission-blue",
        "publication": "admission-sample",
        "publication_digest": pub_digest,
        "service": "lab",
        "artifact": "a-lab",
        "image": expected_image,
    }
    assert len(captured) == 1
    submitted = captured[0]
    assert submitted["metadata"]["namespace"] == "admission-blue"
    assert submitted["metadata"]["labels"]["app.kubernetes.io/name"] == "lab"
    assert submitted["metadata"]["labels"][RUN_LABEL] == "safe-start-7-1"
    assert submitted["metadata"]["annotations"]["rezono.org/artifact"] == "a-lab"
    assert submitted["spec"]["containers"][0]["image"] == expected_image

    # Counterexample: denial stderr missing the reconciled publication digest is rejected.
    def wrong_digest_runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[3:] == ["create", "--dry-run=server", "-f", "-"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="verified-supply: wrong digest")
        return fake_runner(args, **kwargs)

    cluster.runner = wrong_digest_runner
    with pytest.raises(RuntimeError, match="verified-supply admission denial"):
        cluster.verify_unsigned_admission_denial(unsigned)
