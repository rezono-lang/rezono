"""Run certified live startup rounds on the shared disposable Kind fixture."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from ipaddress import IPv4Address, ip_address
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic, sleep, time_ns
from typing import Any
from urllib.parse import urlsplit

from loop.batch_selection import select_batch
from loop.cluster.network_hubble import Hubble
from loop.round_claim import claim_attempt
from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_checker.evidence import Evidence, admit
from rezono_checker.transition import check_transition_certificate
from rezono_compiler import batch as compiler_batch
from rezono_compiler import facts as compiler_facts
from rezono_compiler import pack as compiler_pack
from rezono_compiler import rules as compiler_rules
from rezono_compiler import scenarios as compiler_scenarios
from rezono_publisher import store

ROOT = Path(__file__).resolve().parents[1]
PLATFORM_PACK = ROOT / "examples" / "platform"
PLATFORM_FACTS = PLATFORM_PACK / "facts" / "core.yaml"
PROBE_SOURCE = ROOT / "loop" / "cluster" / "network_probe.go"
CONTEXT = "kind-rezono-fixture"
CLUSTER_NAME = "rezono-fixture"
RECORDER_NAMESPACE = "rezono-probes"
PROBE_IMAGE = "docker.io/library/rezono-network-fixture:local"
MARKER_PORT = 8090
MANIFEST_ID = "platform-safe-startup"
RUN_LABEL = "rezono.org/safe-start-run"
ROLE_LABEL = "rezono.org/role"
ZONE_LABEL = "rezono.org/zone"
SERVICE_LABEL = "rezono.org/service"
CUT_LABEL = "rezono.org/cut"
BOUNDARY_ROLE = "boundary-recorder"
INVARIANTS = ("unprotected_exposure", "exposed_without_namespace")
RUN_ID_RE = re.compile(r"[a-z0-9](?:[-a-z0-9]{0,46}[a-z0-9])?")


def _relation(name: str, role: str, columns: tuple[str, ...], *, invariant: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": name,
        "role": role,
        "key": [{"name": column, "type": "string"} for column in columns],
    }
    if role == "derived":
        entry["module"] = "startup"
    if invariant:
        entry["invariant"] = True
    return entry


def _literal(relation: str, *terms: str, negative: bool = False, stratum: str = "0") -> dict[str, Any]:
    return {
        "relation": relation,
        "terms": list(terms),
        "polarity": "negative" if negative else "positive",
        "stratum": stratum,
    }


def _rule(
    name: str,
    head: tuple[str, ...],
    body: list[dict[str, Any]],
    *,
    line: int,
    stratum: str = "0",
) -> dict[str, Any]:
    return {
        "id": name,
        "module": "startup",
        "stratum": stratum,
        "head": {"relation": name, "terms": list(head)},
        "body": body,
        "origin": {"file": "startup.dl", "line": str(line)},
    }


def _row_ref(relation: str, cells: Iterable[str]) -> dict[str, str]:
    return {"relation": relation, "key": canonical_json(list(cells))}


STARTUP_PROGRAM: dict[str, Any] = compiler_rules.with_strata({
    "format": "rezono.rules/1",
    "pack": MANIFEST_ID,
    "relations": [
        _relation("managed_namespace", "base", ("namespace",)),
        _relation("endpoint_protected", "base", ("endpoint",)),
        _relation("endpoint_exposed", "base", ("endpoint",)),
        _relation("endpoint_namespace", "base", ("endpoint", "namespace")),
        _relation("namespace_active", "derived", ("namespace",)),
        _relation("unprotected_exposure", "derived", ("endpoint",), invariant=True),
        _relation("exposed_without_namespace", "derived", ("endpoint",), invariant=True),
    ],
    "rules": [
        _rule("namespace_active", ("?ns",), [_literal("managed_namespace", "?ns")], line=1),
        _rule(
            "unprotected_exposure",
            ("?ep",),
            [
                _literal("endpoint_exposed", "?ep"),
                _literal("endpoint_protected", "?ep", negative=True),
            ],
            line=2,
            stratum="1",
        ),
        _rule(
            "exposed_without_namespace",
            ("?ep",),
            [
                _literal("endpoint_exposed", "?ep"),
                _literal("endpoint_namespace", "?ep", "?ns"),
                _literal("managed_namespace", "?ns", negative=True),
            ],
            line=3,
            stratum="1",
        ),
    ],
})

TOPOLOGY_DERIVED_RELATIONS = (
    "flow",
    "provides",
    "recovery_reaches_out",
    "unverified_supply",
    "verified",
    "zone_of",
)
TOPOLOGY_BASE_RELATIONS = (
    "artifact__for_service",
    "artifact__signed",
    "zone__entry_boundary",
    "zone__workload",
)


@dataclass(frozen=True)
class NetworkCaseSpec:
    case_id: str
    source_service: str
    source_zone: str
    destination_service: str
    destination_zone: str
    port: int
    expected: str
    function: str


@dataclass(frozen=True)
class StartupTopology:
    zones: tuple[str, ...]
    endpoints: tuple[tuple[str, str, int], ...]  # (service, zone, port)
    endpoint_zones: Mapping[str, str]  # endpoint_id -> zone
    cases: tuple[NetworkCaseSpec, ...]
    prohibited_recovery_flow: dict[str, str]
    unsigned_artifact: dict[str, str]


@dataclass(frozen=True)
class EndpointProtectionSpec:
    endpoint: str
    zone: str
    service: str
    namespace: str
    pod_selector: dict[str, Any]
    ingress: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RoundStep:
    step_id: str
    priority: int
    plan_hash: str
    writes: frozenset[str]
    delta: tuple[tuple[str, tuple[str, ...], int], ...]


@lru_cache(maxsize=1)
def _startup_program() -> compiler_rules.Program:
    return compiler_rules.load(STARTUP_PROGRAM, require_witness=False)


@lru_cache(maxsize=4)
def _load_platform_pack(pack_dir: Path) -> tuple[compiler_pack.Pack, compiler_rules.Program, frozenset[str]]:
    model = compiler_pack.read(pack_dir)
    if not model.rules:
        raise RuntimeError(f"pack {pack_dir} defines no rule program")
    program = compiler_rules.load(model.rules)
    derived_set = set(program.derived())
    needed: set[str] = set()
    stack = [name for name in TOPOLOGY_DERIVED_RELATIONS if name in derived_set]
    while stack:
        relation = stack.pop()
        if relation in needed:
            continue
        needed.add(relation)
        stack.extend(dep for dep in program.deps(relation) if dep in derived_set and dep not in needed)
    return model, program, frozenset(needed)


def _select_topology_from_relations(relations: Mapping[str, set[tuple[str, ...]]]) -> StartupTopology:
    """Build the startup topology from compiler-derived pack relations without re-implementing rules."""
    zone_by_service = {svc: zone for svc, zone in relations["zone_of"]}
    flows = sorted((src, dst, fn, int(port)) for src, dst, fn, port in relations["flow"])
    recovery_prohibited = set(relations["recovery_reaches_out"])
    prohibited = sorted(
        (src, dst, fn, port)
        for src, dst, fn, port in flows
        if (src, dst, fn) in recovery_prohibited
    )
    if not prohibited:
        raise RuntimeError("No prohibited recovery flow derived by platform pack rules")
    bad_src, bad_dst, bad_fn, bad_port = prohibited[0]

    # Select an explicitly unsigned ("no") artifact for a service derived as unverified_supply.
    # Missing/unknown artifact__signed rows are never treated as "no".
    unverified_services = {svc for (svc,) in relations["unverified_supply"]}
    explicitly_unsigned = {art_id for art_id, signed in relations["artifact__signed"] if signed == "no"}
    unsigned_artifacts = sorted(
        (svc, art_id)
        for art_id, svc in relations["artifact__for_service"]
        if svc in unverified_services and art_id in explicitly_unsigned
    )
    if not unsigned_artifacts:
        raise RuntimeError("No explicitly unsigned artifact derived for unverified_supply services")
    unsigned_service, unsigned_artifact_id = unsigned_artifacts[0]

    entry_zones = {zone for zone, flag in relations["zone__entry_boundary"] if flag == "yes"}
    entry_services = sorted(svc for svc, zone in zone_by_service.items() if zone in entry_zones)
    if not entry_services:
        raise RuntimeError("No entry-boundary service derived from platform pack")
    entry_svc = entry_services[0]
    entry_ports = sorted(int(port) for svc, _, port in relations["provides"] if svc == entry_svc)
    entry_port = entry_ports[0] if entry_ports else bad_port
    # Use an unprivileged container port (>= 1024) for the non-root scratch listener.
    entry_listen_port = entry_port if entry_port >= 1024 else 8443
    dst_listen_port = bad_port if bad_port >= 1024 else 8443

    verified_services = {svc for (svc,) in relations["verified"]}
    workload_zones = {zone for zone, flag in relations["zone__workload"] if flag == "yes"}
    authorized_workload = sorted(
        (src, fn, port)
        for src, dst, fn, port in flows
        if dst == bad_dst and src in verified_services and zone_by_service.get(src) in workload_zones
    )
    if not authorized_workload:
        raise RuntimeError("No verified workload flow derived from platform pack")
    workload_svc, workload_fn, _ = authorized_workload[0]

    selected_services = (
        (entry_svc, zone_by_service[entry_svc], entry_listen_port),
        (bad_dst, zone_by_service[bad_dst], dst_listen_port),
        (workload_svc, zone_by_service[workload_svc], 8080),
        (bad_src, zone_by_service[bad_src], 8080),
    )
    managed_zones = tuple(sorted({zone for _, zone, _ in selected_services}))
    endpoint_zones = {
        f"{zone_by_service[entry_svc]}/{entry_svc}": zone_by_service[entry_svc],
        f"{zone_by_service[bad_dst]}/{bad_dst}": zone_by_service[bad_dst],
    }

    cases = (
        NetworkCaseSpec(
            case_id=f"{entry_svc}-to-{bad_dst}",
            source_service=entry_svc,
            source_zone=zone_by_service[entry_svc],
            destination_service=bad_dst,
            destination_zone=zone_by_service[bad_dst],
            port=dst_listen_port,
            expected="allow",
            function=bad_fn,
        ),
        NetworkCaseSpec(
            case_id=f"{workload_svc}-to-{bad_dst}",
            source_service=workload_svc,
            source_zone=zone_by_service[workload_svc],
            destination_service=bad_dst,
            destination_zone=zone_by_service[bad_dst],
            port=dst_listen_port,
            expected="allow",
            function=workload_fn,
        ),
        NetworkCaseSpec(
            case_id=f"{bad_src}-to-{bad_dst}",
            source_service=bad_src,
            source_zone=zone_by_service[bad_src],
            destination_service=bad_dst,
            destination_zone=zone_by_service[bad_dst],
            port=dst_listen_port,
            expected="deny",
            function=bad_fn,
        ),
    )

    return StartupTopology(
        zones=managed_zones,
        endpoints=selected_services,
        endpoint_zones=endpoint_zones,
        cases=cases,
        prohibited_recovery_flow={"source": bad_src, "destination": bad_dst, "function": bad_fn},
        unsigned_artifact={"service": unsigned_service, "artifact": unsigned_artifact_id},
    )


def load_startup_topology(
    facts_path: Path = PLATFORM_FACTS,
    *,
    pack_dir: Path = PLATFORM_PACK,
) -> StartupTopology:
    """Evaluate the platform pack via rezono_compiler and derive the startup topology."""
    pack_root = Path(pack_dir).resolve()
    facts_file = Path(facts_path)
    model, program, needed_derived = _load_platform_pack(pack_root)
    fact_rows = compiler_facts.load(model, facts_file)
    facts_dir = pack_root / "facts"
    resolved_facts = facts_file.resolve()
    sig_facts = facts_dir / "artifact_signature.yaml"
    if (
        sig_facts.is_file()
        and resolved_facts.parent == sig_facts.resolve().parent
        and resolved_facts != sig_facts.resolve()
        and not any(k in fact_rows for k in ("artifact_signature", "signature_scan"))
    ):
        for table, rows in compiler_facts.load(model, sig_facts).items():
            fact_rows.setdefault(table, []).extend(rows)
    port_decisions = facts_dir / "port_decision.yaml"
    if (
        port_decisions.is_file()
        and resolved_facts != port_decisions.resolve()
        and "port_decision" not in fact_rows
    ):
        for table, rows in compiler_facts.load(model, port_decisions).items():
            fact_rows.setdefault(table, []).extend(rows)
    if "vendor_default_transport_source" not in fact_rows:
        for transport_file in sorted(facts_dir.glob("*_transport_source.yaml")):
            if resolved_facts == transport_file.resolve():
                continue
            for table, rows in compiler_facts.load(model, transport_file).items():
                fact_rows.setdefault(table, []).extend(rows)
    inputs = compiler_scenarios.rule_rows(model, program, fact_rows)
    base_requested = tuple(rel for rel in TOPOLOGY_BASE_RELATIONS if rel in program.relations)
    requested = (*TOPOLOGY_DERIVED_RELATIONS, *base_requested)
    with compiler_batch.connect(program, inputs) as con:
        compiler_batch.compute(con, program, relations=needed_derived)
        relations = compiler_batch.read(con, program, requested)
    for rel in TOPOLOGY_BASE_RELATIONS:
        if rel not in relations:
            relations[rel] = {tuple(map(str, row)) for row in fact_rows.get(rel, ())}
    return _select_topology_from_relations(relations)


def build_snapshot(
    label: str,
    *,
    managed_namespaces: Iterable[str],
    protected_endpoints: Iterable[str],
    exposed_endpoints: Iterable[str],
    endpoint_namespaces: Mapping[str, str],
) -> dict[str, Any]:
    """Build a witnessed snapshot for STARTUP_PROGRAM via rezono_compiler.batch."""
    base_rows: dict[str, list[tuple[str, ...]]] = {
        "managed_namespace": [(ns,) for ns in sorted(set(managed_namespaces))],
        "endpoint_protected": [(ep,) for ep in sorted(set(protected_endpoints))],
        "endpoint_exposed": [(ep,) for ep in sorted(set(exposed_endpoints))],
        "endpoint_namespace": sorted((ep, ns) for ep, ns in endpoint_namespaces.items()),
    }
    program = _startup_program()
    with compiler_batch.connect(program, base_rows) as con:
        compiler_batch.compute(con, program)
        derived_rows = compiler_batch.read(con, program)
        raw_witnesses = compiler_batch.witnesses(con, program)

    witnesses: list[dict[str, Any]] = []
    for rule_id, substitutions in sorted(raw_witnesses.items()):
        rule = program.rules[rule_id]
        for values in substitutions:
            env = dict(zip(rule.variables, values, strict=True))
            conclusion_cells = [env[t] if compiler_rules.is_var(t) else t for t in rule.head.terms]
            premises = [
                {
                    "row": _row_ref(
                        lit.atom.relation,
                        [env[t] if compiler_rules.is_var(t) else t for t in lit.atom.terms],
                    ),
                    "polarity": lit.polarity,
                    "stratum": lit.stratum,
                }
                for lit in rule.body
            ]
            witnesses.append({
                "rule_id": rule_id,
                "conclusion": _row_ref(rule.head.relation, conclusion_cells),
                "bindings": [{"variable": var, "value": val} for var, val in zip(rule.variables, values, strict=True)],
                "premises": premises,
            })

    rows = {**base_rows, **{name: sorted(entries) for name, entries in derived_rows.items()}}
    return {"id": label, "rows": rows, "witnesses": witnesses}


def _apply_delta_to_state(
    managed_namespaces: set[str],
    protected_endpoints: set[str],
    exposed_endpoints: set[str],
    delta: Iterable[tuple[str, tuple[str, ...], int]],
) -> tuple[set[str], set[str], set[str]]:
    ns = set(managed_namespaces)
    prot = set(protected_endpoints)
    exp = set(exposed_endpoints)
    tables = {
        "managed_namespace": ns,
        "endpoint_protected": prot,
        "endpoint_exposed": exp,
    }
    for relation, key, weight in delta:
        target = tables[relation]
        if weight == 1:
            target.add(key[0])
        elif weight == -1:
            target.remove(key[0])
        else:
            raise ValueError(f"unsupported delta weight {weight}")
    return ns, prot, exp


def _obs_ref(group: str, name: str, body: bytes) -> dict[str, str]:
    file_path = f"observations/{group}/{name}.json"
    return {"file": file_path, "uri": f"s3://rezono/{file_path}", "sha256": sha256_hex(body)}


def certify_and_select_round(
    archive: store.FileStore,
    *,
    run: str,
    cut: str,
    event_time: int,
    base_namespaces: set[str],
    base_protected: set[str],
    base_exposed: set[str],
    endpoint_namespaces: Mapping[str, str],
    candidates: tuple[RoundStep, ...],
    width: int,
) -> tuple[tuple[RoundStep, ...], str, str]:
    """Check visible subsets, select the certified batch, admit via Evidence, and claim plan hashes."""
    obs_id = f"read-{cut}"
    observed_bytes = canonical_bytes({
        "id": obs_id,
        "run": run,
        "scope": "platform-startup",
        "cut": cut,
        "event_time": event_time,
    })
    cut_binding = {
        "id": cut,
        "run": run,
        "scope": "platform-startup",
        "observation_sha256": sha256_hex(observed_bytes),
    }
    definition_sha = canonical_sha256(STARTUP_PROGRAM)
    cert_context = {
        "manifest": MANIFEST_ID,
        "definition_sha256": definition_sha,
        "program": STARTUP_PROGRAM,
        "invariants": INVARIANTS,
        "cut": cut_binding,
        "observations": {obs_id: observed_bytes},
    }
    base_snapshot = build_snapshot(
        f"base-{cut}",
        managed_namespaces=base_namespaces,
        protected_endpoints=base_protected,
        exposed_endpoints=base_exposed,
        endpoint_namespaces=endpoint_namespaces,
    )
    base_sha = canonical_sha256(base_snapshot)

    # First verify the base snapshot itself with an empty-delta identity certificate.
    base_cert = {
        "manifest": MANIFEST_ID,
        "definition_sha256": definition_sha,
        "run": run,
        "cut": cut,
        "base": base_sha,
        "variant": base_sha,
        "rule": "opening-base",
        "bindings": {"cut": cut},
        "effect": canonical_sha256([]),
        "expected_old": [],
        "delta": [],
        "invariants": {inv: {"rows": [], "count": "0"} for inv in INVARIANTS},
    }
    base_report = check_transition_certificate(base_cert, cert_context, base_snapshot, base_snapshot)
    if not base_report["valid"]:
        raise RuntimeError(f"Base snapshot failed certification at {cut}: {base_report['findings']}")

    if not candidates:
        return (), canonical_sha256(base_cert), ""

    step_by_id = {step.step_id: step for step in candidates}
    ordered_ids = tuple(step.step_id for step in sorted(candidates, key=lambda s: s.priority))
    priorities = {step.step_id: step.priority for step in candidates}
    effects_map = {step.step_id: {"write": step.writes} for step in candidates}

    # Evaluate every nonempty subset up to width against check_transition_certificate.
    from itertools import combinations

    verdicts: dict[frozenset[str], bool] = {frozenset(): True}
    subset_artifacts: dict[frozenset[str], tuple[list[str], dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = {}
    for size in range(1, min(width, len(ordered_ids)) + 1):
        for combo in combinations(ordered_ids, size):
            combo_steps = tuple(step_by_id[sid] for sid in combo)
            combined_delta = [change for step in combo_steps for change in step.delta]
            plan_hashes = [step.plan_hash for step in combo_steps]
            next_ns, next_prot, next_exp = _apply_delta_to_state(
                base_namespaces, base_protected, base_exposed, combined_delta
            )
            variant = build_snapshot(
                f"variant-{cut}-{'-'.join(combo)}",
                managed_namespaces=next_ns,
                protected_endpoints=next_prot,
                exposed_endpoints=next_exp,
                endpoint_namespaces=endpoint_namespaces,
            )
            expected_old = [
                _row_ref(rel, key) for rel, key, weight in combined_delta if weight == -1
            ]
            certificate = {
                "manifest": MANIFEST_ID,
                "definition_sha256": definition_sha,
                "run": run,
                "cut": cut,
                "base": base_sha,
                "variant": canonical_sha256(variant),
                "rule": f"round-{cut}",
                "bindings": {"steps": ",".join(combo)},
                "effect": canonical_sha256(plan_hashes),
                "expected_old": expected_old,
                "delta": combined_delta,
                "invariants": {inv: {"rows": [], "count": "0"} for inv in INVARIANTS},
            }
            report = check_transition_certificate(certificate, cert_context, base_snapshot, variant)
            verdicts[frozenset(combo)] = bool(report["valid"])
            subset_artifacts[frozenset(combo)] = (plan_hashes, variant, certificate, report["findings"])

    selection = select_batch(priorities, verdicts, effects=effects_map, width=width)
    chosen_ids = tuple(sid for sid in ordered_ids if sid in selection["selected"])
    if not chosen_ids:
        raise RuntimeError(f"No certified batch available at cut {cut}")

    # Assemble retained & submitted archived evidence and verify with rezono_checker.evidence.admit.
    round_archive_prefix = f"{cut}-"
    retained: dict[str, bytes] = {
        f"{round_archive_prefix}definition": canonical_bytes(STARTUP_PROGRAM),
        f"{round_archive_prefix}observed": observed_bytes,
        f"{round_archive_prefix}base": canonical_bytes(base_snapshot),
        f"{round_archive_prefix}domain": canonical_bytes({
            "width": width,
            "steps": [
                {"step": step.step_id, "priority": step.priority, "effects": [step.plan_hash]}
                for step in sorted(candidates, key=lambda s: s.priority)
            ],
        }),
    }
    submitted: dict[str, bytes] = {}
    claim_subsets: list[dict[str, Any]] = []

    def add_subset(member_ids: tuple[str, ...]) -> None:
        key = frozenset(member_ids)
        plan_hashes, variant, certificate, _ = subset_artifacts[key]
        slug = "-".join(member_ids)
        v_name = f"{round_archive_prefix}variant-{slug}"
        c_name = f"{round_archive_prefix}cert-{slug}"
        submitted[v_name] = canonical_bytes(variant)
        submitted[c_name] = canonical_bytes(certificate)
        claim_subsets.append({
            "members": list(member_ids),
            "effects": plan_hashes,
            "variant": _obs_ref("submitted", v_name, submitted[v_name]),
            "certificate": _obs_ref("submitted", c_name, submitted[c_name]),
        })

    included: set[frozenset[str]] = set()
    for size in range(1, len(chosen_ids) + 1):
        for sub in combinations(chosen_ids, size):
            included.add(frozenset(sub))
            add_subset(sub)

    # Also attach refuting boundaries for every larger or higher-priority alternative.
    chosen_rank = (-len(chosen_ids), tuple(priorities[sid] for sid in chosen_ids))
    for size in range(min(width, len(ordered_ids)), 0, -1):
        for alt in combinations(ordered_ids, size):
            alt_rank = (-len(alt), tuple(priorities[sid] for sid in alt))
            if alt_rank >= chosen_rank:
                continue
            for sub_size in range(1, len(alt) + 1):
                for sub in combinations(alt, sub_size):
                    sub_key = frozenset(sub)
                    if sub_key in included:
                        continue
                    _, _, _, findings = subset_artifacts[sub_key]
                    if any(f.get("snapshot") == "variant" and f["reason"] == "invariant_violated" for f in findings):
                        included.add(sub_key)
                        add_subset(sub)

    batch_name = f"batch-{cut}"
    claim_name = f"{round_archive_prefix}claim"
    submitted[claim_name] = canonical_bytes({
        "run": run,
        "cut": cut,
        "batch": batch_name,
        "members": list(chosen_ids),
        "subsets": claim_subsets,
    })
    claim_ref = _obs_ref("submitted", claim_name, submitted[claim_name])

    for group, objects in (("retained", retained), ("submitted", submitted)):
        for name, body in objects.items():
            ref = _obs_ref(group, name, body)
            if archive.get(ref["file"]) is None:
                archive.put_new(ref["file"], body)

    def pinned_ret(name: str) -> dict[str, str]:
        return _obs_ref("retained", name, retained[name])

    context_obj = {
        "completeness": [],
        "rounds": [{
            "run": run,
            "cut": cut_binding,
            "manifest": MANIFEST_ID,
            "definition_sha256": sha256_hex(retained[f"{round_archive_prefix}definition"]),
            "program": pinned_ret(f"{round_archive_prefix}definition"),
            "invariants": list(INVARIANTS),
            "observations": {obs_id: pinned_ret(f"{round_archive_prefix}observed")},
            "base": pinned_ret(f"{round_archive_prefix}base"),
            "domain": pinned_ret(f"{round_archive_prefix}domain"),
        }],
    }
    index_obj = {"completeness_receipts": [], "rounds": [claim_ref]}
    context_body = canonical_bytes(context_obj)
    index_body = canonical_bytes(index_obj)
    context_ref = _obs_ref("retained", f"{round_archive_prefix}context", context_body)
    index_ref = _obs_ref("submitted", f"{round_archive_prefix}index", index_body)
    archive.put_new(context_ref["file"], context_body)
    archive.put_new(index_ref["file"], index_body)

    evidence = Evidence(
        context_ref,
        index_ref,
        lambda uri: archive.get(uri.removeprefix(archive.uri(""))),
    )
    admitted = admit(evidence)
    if admitted.findings:
        raise RuntimeError(f"Round admission failed at {cut}: {admitted.findings}")
    if admitted.rows["verified_round"] != [(claim_ref["sha256"], run, cut, batch_name)]:
        raise RuntimeError(f"Round {cut} was not admitted cleanly: {admitted.rows['verified_round']}")

    # Durably claim every chosen step's plan hash before dispatching to the cluster.
    chosen_steps = tuple(step_by_id[sid] for sid in chosen_ids)
    for step in chosen_steps:
        claimed = claim_attempt(archive, plan_hash=step.plan_hash, run=run, cut=cut, worker="startup-executor")
        if claimed is None:
            raise RuntimeError(f"Plan hash {step.plan_hash} for step {step.step_id} was already claimed")

    _, _, full_cert, _ = subset_artifacts[frozenset(chosen_ids)]
    return chosen_steps, canonical_sha256(full_cert), claim_ref["sha256"]


def _run_cmd(
    args: list[str],
    *,
    data: str | None = None,
    timeout: int = 30,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=data,
        check=check,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        env=dict(env) if env is not None else None,
    )


class StartupCluster:
    """Kubectl, Hubble and recorder-Job adapter over the runner-local Kind fixture."""

    def __init__(
        self,
        kubeconfig: Path,
        run: str,
        *,
        env: Mapping[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        hubble_factory: Callable[[list[str]], Any] | None = None,
        settle_seconds: float = 2.0,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.runner = _run_cmd if runner is None else runner
        self.hubble_factory = Hubble if hubble_factory is None else hubble_factory
        self.settle_seconds = settle_seconds
        self.run = run
        if not isinstance(run, str) or not RUN_ID_RE.fullmatch(run):
            raise ValueError(f"invalid safe-start run identifier: {run!r}")

        config = Path(kubeconfig).resolve(strict=True)
        admission_config = self.env.get("REZONO_ADMISSION_TEST_KUBECONFIG")
        if not admission_config or not config.samefile(admission_config):
            raise RuntimeError("startup requires the shared admission handoff kubeconfig")
        temp_root = self.env.get("RUNNER_TEMP")
        if temp_root and not config.is_relative_to(Path(temp_root).resolve(strict=True)):
            raise RuntimeError("startup kubeconfig must live inside RUNNER_TEMP")

        base = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
        if self._out([*base, "config", "current-context"]).strip() != CONTEXT:
            raise RuntimeError("unexpected kubectl current-context")
        server = self._out([*base, "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]).strip()
        host = urlsplit(server).hostname
        if not host or not ip_address(host).is_loopback:
            raise RuntimeError("fixture API server must be runner-local")

        self.command = [*base, "--context", CONTEXT]
        nodes = self.get("nodes")["items"]
        if len(nodes) != 1:
            raise RuntimeError(f"expected single local kind node, found {len(nodes)}")
        self.node = nodes[0]["metadata"]["name"]
        self.cilium_pod = self._wait_cilium_ready()
        self._verify_admission_reconciled()

    def _out(self, cmd: list[str], *, data: str | None = None, timeout: int = 30) -> str:
        return self.runner(cmd, data=data, timeout=timeout, check=True).stdout

    def get(self, *args: str, namespace: str | None = None, timeout: int = 25) -> dict[str, Any]:
        cmd = [*self.command, *(["-n", namespace] if namespace else []), "get", *args, "-o", "json"]
        return json.loads(self._out(cmd, timeout=timeout))

    def apply(self, manifest: dict[str, Any], timeout: int = 25) -> None:
        self._out([*self.command, "apply", "-f", "-"], data=json.dumps(manifest), timeout=timeout)

    def _wait_cilium_ready(self) -> str:
        deadline = monotonic() + 30.0
        while True:
            pods = self.get("pods", "-l", "k8s-app=cilium", namespace="kube-system")["items"]
            ready = [
                pod["metadata"]["name"]
                for pod in pods
                if pod.get("spec", {}).get("nodeName") == self.node
                and any(c.get("type") == "Ready" and c.get("status") == "True"
                        for c in pod.get("status", {}).get("conditions", ()))
            ]
            if len(ready) == 1:
                return ready[0]
            if monotonic() >= deadline:
                raise RuntimeError("expected one ready Cilium agent on the fixture node")
            sleep(1.0)

    def _verify_admission_reconciled(self) -> None:
        app_ns = self.env.get("REZONO_ADMISSION_TEST_APPLICATION_NAMESPACE", "argocd")
        app_name = self.env.get("REZONO_ADMISSION_TEST_APPLICATION", "rezono-admission")
        app = self.get("applications.argoproj.io", app_name, namespace=app_ns)
        if app.get("status", {}).get("sync", {}).get("status") != "Synced":
            raise RuntimeError("shared admission application is not Synced")
        publications = sorted(
            (row.get("namespace", ""), row["name"])
            for row in app.get("status", {}).get("resources", ())
            if row.get("kind") == "NamespacePublication"
            and row.get("status") == "Synced"
            and row.get("namespace")
            and row.get("name")
        )
        if not publications:
            raise RuntimeError("shared admission application has no Synced NamespacePublication")
        self.admission_namespace, self.admission_publication = publications[0]

    def ensure_probe_image(self) -> None:
        """Reuse the preloaded probe image on the Kind node, or build and load it."""
        listed = self.runner(
            ["docker", "exec", self.node, "ctr", "-n", "k8s.io", "images", "ls", "-q"],
            timeout=20,
            check=False,
        )
        if listed.returncode == 0 and PROBE_IMAGE in listed.stdout.splitlines():
            return
        with TemporaryDirectory(prefix="rezono-startup-probe-") as tmpdir:
            directory = Path(tmpdir)
            probe_bin = directory / "network-probe"
            go_env = {
                **self.env,
                "CGO_ENABLED": "0",
                "GOOS": "linux",
                "GOARCH": "amd64",
                "GOTOOLCHAIN": "local",
                "GO111MODULE": "off",
            }
            self.runner(
                ["go", "build", "-trimpath", "-buildvcs=false", "-ldflags=-buildid=",
                 "-o", str(probe_bin), str(PROBE_SOURCE)],
                timeout=90,
                env=go_env,
                check=True,
            )
            (directory / "Dockerfile").write_text(
                "FROM scratch\nCOPY network-probe /network-probe\nUSER 65534:65534\n",
                encoding="utf-8",
            )
            self.runner(["docker", "build", "--network=none", "--tag", PROBE_IMAGE, str(directory)], timeout=60)
            try:
                self.runner(["kind", "load", "docker-image", PROBE_IMAGE, "--name", CLUSTER_NAME], timeout=60)
            finally:
                self.runner(["docker", "image", "rm", "--no-prune", PROBE_IMAGE], timeout=30, check=False)

    def managed_namespaces(self) -> list[str]:
        items = self.get("namespaces", "-l", f"{RUN_LABEL}={self.run}")["items"]
        return sorted(item["metadata"]["name"] for item in items)

    def managed_network_policies(self) -> list[dict[str, Any]]:
        return self.get("networkpolicies", "-A", "-l", f"{RUN_LABEL}={self.run}")["items"]

    def managed_pods(self) -> list[dict[str, Any]]:
        return self.get("pods", "-A", "-l", f"{RUN_LABEL}={self.run}")["items"]

    def wait_pods_ready(self, namespaces: Iterable[str]) -> None:
        for ns in sorted(set(namespaces)):
            self._out(
                [*self.command, "-n", ns, "wait", "pods", "-l", f"{RUN_LABEL}={self.run}",
                 "--for=condition=Ready", "--timeout=45s"],
                timeout=50,
            )

    def pod_ip(self, namespace: str, pod: str) -> str:
        obj = self.get("pod", pod, namespace=namespace)
        return str(IPv4Address(obj["status"]["podIP"]))

    def pod_probe(self, namespace: str, pod: str, target_ip: str, port: int) -> tuple[bool, int]:
        res = self.runner(
            [*self.command, "-n", namespace, "exec", pod, "--", "/network-probe", "probe", target_ip, str(port)],
            timeout=15,
            check=False,
        )
        status = res.stdout.strip()
        if res.returncode != 0 or status not in {"0", "1", "124"}:
            raise RuntimeError(f"probe from {namespace}/{pod} failed: {res.stderr.strip()}")
        return status == "0", int(status)

    def verify_unsigned_admission_denial(self, unsigned_artifact: Mapping[str, str]) -> dict[str, Any]:
        """Verify live server-side admission rejects the derived unsigned artifact's image digest."""
        service = unsigned_artifact["service"]
        artifact = unsigned_artifact["artifact"]
        image = _unsigned_artifact_image(unsigned_artifact)
        publication = self.get(
            "namespacepublications.admission.rezono.org",
            self.admission_publication,
            namespace=self.admission_namespace,
        )
        spec = publication.get("spec", {})
        pub_digest = spec.get("digest", "")
        if not isinstance(pub_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", pub_digest):
            raise RuntimeError(f"invalid reconciled NamespacePublication digest: {pub_digest!r}")
        admitted_images = {
            (row.get("service"), row.get("image"))
            for row in spec.get("images", ())
            if isinstance(row, dict)
        }
        if (service, image) in admitted_images:
            raise RuntimeError(f"unsigned artifact {artifact} for service {service} is unexpectedly published")
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"unsigned-{service}-{artifact}"[:63].rstrip("-"),
                "namespace": self.admission_namespace,
                "labels": {
                    "app.kubernetes.io/name": service,
                    RUN_LABEL: self.run,
                    SERVICE_LABEL: service,
                },
                "annotations": {"rezono.org/artifact": artifact},
            },
            "spec": {
                "automountServiceAccountToken": False,
                "securityContext": {
                    "runAsNonRoot": True,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [{
                    "name": "app",
                    "image": image,
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                    },
                }],
            },
        }
        result = self.runner(
            [*self.command, "create", "--dry-run=server", "-f", "-"],
            data=json.dumps(pod),
            timeout=25,
            check=False,
        )
        compact_stderr = result.stderr.replace(".", "").replace("-", "")
        if result.returncode == 0 or "verified-supply" not in result.stderr or pub_digest not in compact_stderr:
            raise RuntimeError(
                f"expected verified-supply admission denial for {service}/{artifact} "
                f"(publication {pub_digest}), got rc={result.returncode}: {result.stderr}"
            )
        return {
            "denied": True,
            "policy": "verified-supply",
            "namespace": self.admission_namespace,
            "publication": self.admission_publication,
            "publication_digest": pub_digest,
            "service": service,
            "artifact": artifact,
            "image": image,
        }

    def hubble(self) -> Any:
        cmd = [
            *self.command, "-n", "kube-system", "exec", self.cilium_pod, "-c", "cilium-agent", "--",
            "hubble", "observe", "--server", "unix:///var/run/cilium/hubble.sock",
            "--follow", "--output", "jsonpb",
        ]
        return self.hubble_factory(cmd)

    def record_boundary(
        self,
        index: int,
        *,
        cut: str,
        managed_namespaces: list[str],
        protected_endpoints: list[str],
        exposed_endpoints: list[str],
        certificate: str,
        admitted_round: str,
    ) -> dict[str, Any]:
        """Emit one live readback boundary via a native recorder Job and return its reference."""
        self.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": RECORDER_NAMESPACE}})
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        body = {
            "run": self.run,
            "cut": cut,
            "kind": "live_readback",
            "inventory_complete": True,
            "managed_namespaces": sorted(managed_namespaces),
            "protected_endpoints": sorted(protected_endpoints),
            "exposed_endpoints": sorted(exposed_endpoints),
            "certificate": certificate,
            "admitted_round": admitted_round,
            "observed_at": stamp,
        }
        receipt = f"sha256:{canonical_sha256(body)}"
        event = {**body, "receipt": receipt}
        payload = json.dumps(event, sort_keys=True) + "\n"

        job_name = f"{self.run}-b{index}"
        cm_name = f"{job_name}-evidence"
        labels = {RUN_LABEL: self.run, ROLE_LABEL: BOUNDARY_ROLE, CUT_LABEL: cut}
        self.apply({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": cm_name, "namespace": RECORDER_NAMESPACE, "labels": {RUN_LABEL: self.run}},
            "immutable": True,
            "data": {"boundary.jsonl": payload},
        })
        self.apply({
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": job_name, "namespace": RECORDER_NAMESPACE, "labels": labels},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 40,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "nodeName": self.node,
                        "restartPolicy": "Never",
                        "automountServiceAccountToken": False,
                        "containers": [{
                            "name": "recorder",
                            "image": PROBE_IMAGE,
                            "imagePullPolicy": "Never",
                            "command": ["/network-probe", "record", "/evidence/boundary.jsonl"],
                            "volumeMounts": [{"name": "observations", "mountPath": "/evidence", "readOnly": True}],
                        }],
                        "volumes": [{"name": "observations", "configMap": {"name": cm_name}}],
                    },
                },
            },
        })
        self._out(
            [*self.command, "-n", RECORDER_NAMESPACE, "wait", f"job/{job_name}",
             "--for=condition=Complete", "--timeout=45s"],
            timeout=50,
        )
        job = self.get("job", job_name, namespace=RECORDER_NAMESPACE)
        if job.get("status", {}).get("succeeded") != 1:
            raise RuntimeError(f"boundary recorder Job {job_name} did not succeed")
        return {
            "namespace": RECORDER_NAMESPACE,
            "job": job_name,
            "uid": job["metadata"]["uid"],
            "receipt": receipt,
            "cut": cut,
        }


def _unsigned_artifact_image(unsigned_artifact: Mapping[str, str]) -> str:
    service = unsigned_artifact.get("service", "")
    artifact = unsigned_artifact.get("artifact", "")
    if not isinstance(service, str) or not service or not isinstance(artifact, str) or not artifact:
        raise ValueError("unsigned artifact requires non-empty service and artifact identifiers")
    digest = canonical_sha256({"artifact": artifact, "service": service, "signed": "no"})
    return f"registry.example.org/platform/{service}@sha256:{digest}"


def _namespace_name(run: str, zone: str) -> str:
    return f"{run}-{zone}"


def _expected_protections(run: str, topology: StartupTopology) -> dict[str, EndpointProtectionSpec]:
    """Compute the exact namespace, podSelector and ingress rules expected for each protected endpoint."""
    allowed_by_dst: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for case in topology.cases:
        if case.expected != "allow":
            continue
        dst_key = (case.destination_zone, case.destination_service)
        allowed_by_dst.setdefault(dst_key, []).append({
            "from": [{
                "namespaceSelector": {"matchLabels": {RUN_LABEL: run, ZONE_LABEL: case.source_zone}},
                "podSelector": {"matchLabels": {SERVICE_LABEL: case.source_service}},
            }],
            "ports": [{"protocol": "TCP", "port": case.port}],
        })

    # Also allow the Hubble coverage heartbeat on MARKER_PORT from the first allowed case's source to destination.
    heartbeat_case = next(case for case in topology.cases if case.expected == "allow")
    hb_key = (heartbeat_case.destination_zone, heartbeat_case.destination_service)
    allowed_by_dst.setdefault(hb_key, []).append({
        "from": [{
            "namespaceSelector": {"matchLabels": {RUN_LABEL: run, ZONE_LABEL: heartbeat_case.source_zone}},
            "podSelector": {"matchLabels": {SERVICE_LABEL: heartbeat_case.source_service}},
        }],
        "ports": [{"protocol": "TCP", "port": MARKER_PORT}],
    })

    protections: dict[str, EndpointProtectionSpec] = {}
    for ep_id, zone in sorted(topology.endpoint_zones.items()):
        ep_zone, svc = ep_id.split("/", 1)
        if ep_zone != zone:
            raise ValueError(f"endpoint {ep_id!r} zone prefix does not match zone {zone!r}")
        protections[ep_id] = EndpointProtectionSpec(
            endpoint=ep_id,
            zone=zone,
            service=svc,
            namespace=_namespace_name(run, zone),
            pod_selector={"matchLabels": {SERVICE_LABEL: svc}},
            ingress=tuple(allowed_by_dst.get((zone, svc), ())),
        )
    return protections


def _policy_applies_to_ingress(policy_types: Any) -> bool | None:
    """Return whether a NetworkPolicy's policyTypes applies to Ingress, or None if malformed.

    Per Kubernetes networking.k8s.io/v1 semantics, omitted or empty policyTypes
    always applies to Ingress. Ingress is inactive only when policyTypes is a
    non-empty list of valid policy types that omits "Ingress" (i.e. Egress-only).
    """
    if policy_types is None or policy_types == []:
        return True
    if not isinstance(policy_types, list):
        return None
    if not all(isinstance(pt, str) and pt in {"Ingress", "Egress"} for pt in policy_types):
        return None
    return "Ingress" in policy_types


def _read_protected_endpoints(
    policies: list[dict[str, Any]],
    run: str,
    expected_protections: Mapping[str, EndpointProtectionSpec],
) -> list[str]:
    """Derive protected endpoints from live readback of applied NetworkPolicies."""
    default_deny_ns: set[str] = set()
    unsafe_ns: set[str] = set()
    matched_endpoints: set[str] = set()
    compromised_endpoints: set[str] = set()
    seen_policy_names: set[tuple[str, str]] = set()

    for policy in policies:
        if not isinstance(policy, dict):
            return []
        meta = policy.get("metadata")
        if not isinstance(meta, dict):
            return []
        if (
            type(meta.get("generation")) is not int
            or meta["generation"] <= 0
            or not isinstance(meta.get("uid"), str)
            or not meta["uid"]
        ):
            continue
        ns = meta.get("namespace")
        name = meta.get("name")
        if not isinstance(ns, str) or not isinstance(name, str):
            return []
        if (ns, name) in seen_policy_names:
            unsafe_ns.add(ns)
            continue
        seen_policy_names.add((ns, name))

        spec = policy.get("spec")
        if not isinstance(spec, dict):
            unsafe_ns.add(ns)
            continue

        applies_to_ingress = _policy_applies_to_ingress(spec.get("policyTypes"))
        if applies_to_ingress is None:
            unsafe_ns.add(ns)
            continue
        raw_ingress = spec.get("ingress")
        if not applies_to_ingress:
            if raw_ingress is not None and raw_ingress != []:
                unsafe_ns.add(ns)
            continue

        if raw_ingress is None:
            actual_ingress: list[Any] = []
        elif isinstance(raw_ingress, list):
            actual_ingress = raw_ingress
        else:
            unsafe_ns.add(ns)
            continue
        pod_selector = spec.get("podSelector")

        if name == "rezono-default-deny":
            if pod_selector == {} and not actual_ingress:
                default_deny_ns.add(ns)
            else:
                unsafe_ns.add(ns)
            continue

        annotations = meta.get("annotations")
        ep = annotations.get("rezono.org/protected-endpoint") if isinstance(annotations, dict) else None
        if isinstance(ep, str) and ep in expected_protections:
            expected = expected_protections[ep]
            expected_ns = _namespace_name(run, expected.zone)
            expected_name = f"rezono-protect-{expected.service}"
            expected_selector = {"matchLabels": {SERVICE_LABEL: expected.service}}
            if ns != expected_ns:
                unsafe_ns.add(ns)
                continue
            if name == expected_name and pod_selector == expected_selector:
                actual_rules = sorted(canonical_json(rule) for rule in actual_ingress)
                expected_rules = sorted(canonical_json(rule) for rule in expected.ingress)
                if actual_rules == expected_rules:
                    matched_endpoints.add(ep)
                else:
                    compromised_endpoints.add(ep)
                continue
            compromised_endpoints.add(ep)
            unsafe_ns.add(ns)
            continue

        # Any other ingress NetworkPolicy in the namespace is unrecognized.
        # Because Kubernetes NetworkPolicy allow rules are additive across any
        # matching podSelector (empty, matchLabels, matchExpressions, etc.),
        # fail closed for the entire namespace.
        unsafe_ns.add(ns)

    return sorted(
        ep
        for ep in matched_endpoints
        if ep not in compromised_endpoints
        and _namespace_name(run, expected_protections[ep].zone) in default_deny_ns
        and _namespace_name(run, expected_protections[ep].zone) not in unsafe_ns
    )


def _read_exposed_endpoints(
    pods: list[dict[str, Any]],
    run: str,
    expected_endpoints: Mapping[str, str],
) -> list[str]:
    """Derive currently exposed endpoints from live Ready Pod readback."""
    exposed: set[str] = set()
    for pod in pods:
        meta = pod.get("metadata", {})
        labels = meta.get("labels", {})
        zone = labels.get(ZONE_LABEL)
        svc = labels.get(SERVICE_LABEL)
        if not zone or not svc:
            continue
        ep = f"{zone}/{svc}"
        if ep not in expected_endpoints or meta.get("namespace") != _namespace_name(run, expected_endpoints[ep]):
            continue
        ready = any(
            cond.get("type") == "Ready" and cond.get("status") == "True"
            for cond in pod.get("status", {}).get("conditions", ())
        )
        if ready:
            exposed.add(ep)
    return sorted(exposed)


def _apply_namespaces_and_default_deny(cluster: StartupCluster, run: str, topology: StartupTopology) -> None:
    for zone in topology.zones:
        ns = _namespace_name(run, zone)
        cluster.apply({
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": ns, "labels": {RUN_LABEL: run, ZONE_LABEL: zone}},
        })
        cluster.apply({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": "rezono-default-deny",
                "namespace": ns,
                "labels": {RUN_LABEL: run, ZONE_LABEL: zone},
            },
            "spec": {"podSelector": {}, "policyTypes": ["Ingress"]},
        })


def _apply_scoped_protections(
    cluster: StartupCluster,
    run: str,
    expected_protections: Mapping[str, EndpointProtectionSpec],
) -> None:
    for ep_id, expected in sorted(expected_protections.items()):
        spec: dict[str, Any] = {
            "podSelector": expected.pod_selector,
            "policyTypes": ["Ingress"],
        }
        if expected.ingress:
            spec["ingress"] = list(expected.ingress)
        cluster.apply({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": f"rezono-protect-{expected.service}",
                "namespace": expected.namespace,
                "labels": {RUN_LABEL: run, ZONE_LABEL: expected.zone, SERVICE_LABEL: expected.service},
                "annotations": {"rezono.org/protected-endpoint": ep_id},
            },
            "spec": spec,
        })


def _apply_protected_pods(cluster: StartupCluster, run: str, topology: StartupTopology) -> dict[str, tuple[str, str]]:
    heartbeat_case = next(case for case in topology.cases if case.expected == "allow")
    pod_namespaces: list[str] = []
    for svc, zone, port in topology.endpoints:
        ns = _namespace_name(run, zone)
        pod_namespaces.append(ns)
        ports = {port}
        if svc == heartbeat_case.destination_service:
            ports.add(MARKER_PORT)
        cluster.apply({
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": svc,
                "namespace": ns,
                "labels": {RUN_LABEL: run, ZONE_LABEL: zone, SERVICE_LABEL: svc},
            },
            "spec": {
                "nodeName": cluster.node,
                "automountServiceAccountToken": False,
                "restartPolicy": "Never",
                "containers": [{
                    "name": "listener",
                    "image": PROBE_IMAGE,
                    "imagePullPolicy": "Never",
                    "command": ["/network-probe", "serve", *(str(p) for p in sorted(ports))],
                    "readinessProbe": {"tcpSocket": {"port": min(ports)}, "periodSeconds": 1},
                }],
            },
        })
    cluster.wait_pods_ready(pod_namespaces)
    return {svc: (_namespace_name(run, zone), cluster.pod_ip(_namespace_name(run, zone), svc))
            for svc, zone, _ in topology.endpoints}


def _wait_policy_active(
    cluster: StartupCluster,
    src_ns: str,
    src_pod: str,
    dst_ip: str,
    port: int,
    timeout: float = 20.0,
) -> None:
    """Wait until the allowed heartbeat probe succeeds, proving Cilium synced the live NetworkPolicies."""
    deadline = monotonic() + timeout
    while True:
        answered, _ = cluster.pod_probe(src_ns, src_pod, dst_ip, port)
        if answered:
            return
        if monotonic() >= deadline:
            raise RuntimeError("timed out waiting for live NetworkPolicy heartbeat path to open")
        sleep(0.5)


def _run_network_verification(
    cluster: StartupCluster,
    topology: StartupTopology,
    pod_ips: Mapping[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    """Run live socket probes inside a bracketed destination-side Hubble sweep."""
    heartbeat_case = next(case for case in topology.cases if case.expected == "allow")
    hb_src_ns, hb_src_ip = pod_ips[heartbeat_case.source_service]
    _, hb_dst_ip = pod_ips[heartbeat_case.destination_service]

    _wait_policy_active(cluster, hb_src_ns, heartbeat_case.source_service, hb_dst_ip, MARKER_PORT)
    if cluster.settle_seconds > 0:
        sleep(cluster.settle_seconds)

    start = 0
    stop = 0
    probe_results: list[tuple[NetworkCaseSpec, str, str, bool, int]] = []
    captured_flows: list[Any] = []
    last_error: RuntimeError | None = None
    for attempt in range(3):
        try:
            with cluster.hubble() as hubble:
                mark_before = time_ns()
                hubble.heartbeat(
                    hb_src_ip,
                    hb_dst_ip,
                    MARKER_PORT,
                    mark_before,
                    lambda: cluster.pod_probe(hb_src_ns, heartbeat_case.source_service, hb_dst_ip, MARKER_PORT),
                )
                start = time_ns()
                probe_results = []
                for case in topology.cases:
                    src_ns, src_ip = pod_ips[case.source_service]
                    _, dst_ip = pod_ips[case.destination_service]
                    answered, status = cluster.pod_probe(src_ns, case.source_service, dst_ip, case.port)
                    probe_results.append((case, src_ip, dst_ip, answered, status))
                stop = time_ns()
                hubble.heartbeat(
                    hb_src_ip,
                    hb_dst_ip,
                    MARKER_PORT,
                    stop,
                    lambda: cluster.pod_probe(hb_src_ns, heartbeat_case.source_service, hb_dst_ip, MARKER_PORT),
                )
                hubble.drain()
                captured_flows = list(hubble.flows)
                last_error = None
                break
        except RuntimeError as exc:
            last_error = exc
            if attempt == 2 or probe_results:
                raise
            sleep(1.0)
    if last_error is not None:
        raise last_error

    observed_cases: list[dict[str, Any]] = []
    for case, src_ip, dst_ip, answered, status in probe_results:
        probe_outcome = "allow" if answered else "deny"
        if probe_outcome != case.expected:
            raise RuntimeError(f"network case {case.case_id}: expected {case.expected}, probe got {probe_outcome}")
        matches = [
            flow
            for flow in captured_flows
            if (flow.source, flow.destination, flow.port) == (src_ip, dst_ip, case.port)
            and start <= flow.tick < stop
        ]
        verdicts = {flow.outcome for flow in matches}
        if not matches or verdicts != {case.expected}:
            raise RuntimeError(
                f"network case {case.case_id}: expected Hubble {case.expected}, observed {sorted(verdicts)}"
            )
        first = min(matches, key=lambda flow: flow.tick)
        hubble_receipt = f"sha256:{canonical_sha256(first.event)}"
        observed_cases.append({
            "id": case.case_id,
            "source": case.source_service,
            "destination": case.destination_service,
            "port": case.port,
            "expected": case.expected,
            "probe": {"outcome": probe_outcome, "status": status},
            "hubble_receipt": hubble_receipt,
            "hubble_outcome": first.outcome,
            "node": cluster.node,
        })
    return observed_cases


def run_startup(
    kubeconfig: str | Path,
    run: str,
    *,
    cluster: StartupCluster | None = None,
    topology: StartupTopology | None = None,
) -> dict[str, Any]:
    """Execute certified safe startup rounds from empty managed scope to live readiness."""
    topo = load_startup_topology() if topology is None else topology
    live = StartupCluster(Path(kubeconfig), run) if cluster is None else cluster

    live.ensure_probe_image()
    opening_ns = live.managed_namespaces()
    if opening_ns:
        raise RuntimeError(f"managed scope must start empty for run {run}, found {opening_ns}")

    expected_ns = [_namespace_name(run, zone) for zone in topo.zones]
    expected_endpoints = set(topo.endpoint_zones)
    endpoint_namespaces = {ep: _namespace_name(run, zone) for ep, zone in topo.endpoint_zones.items()}

    boundaries: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="rezono-startup-archive-") as archive_dir:
        archive = store.FileStore(Path(archive_dir))

        # Boundary 0: verify and record the empty opening base.
        _, opening_cert, _ = certify_and_select_round(
            archive,
            run=run,
            cut="opening",
            event_time=1,
            base_namespaces=set(),
            base_protected=set(),
            base_exposed=set(),
            endpoint_namespaces=endpoint_namespaces,
            candidates=(),
            width=1,
        )
        boundaries.append(
            live.record_boundary(
                0,
                cut="opening",
                managed_namespaces=[],
                protected_endpoints=[],
                exposed_endpoints=[],
                certificate=opening_cert,
                admitted_round="",
            )
        )

        # Round 1: prepare isolated managed namespaces and default-deny NetworkPolicies.
        ns_delta = tuple(("managed_namespace", (ns,), 1) for ns in sorted(expected_ns))
        prepare_ns_step = RoundStep(
            step_id="prepare-namespaces",
            priority=0,
            plan_hash=canonical_sha256({"run": run, "step": "prepare-namespaces", "namespaces": sorted(expected_ns)}),
            writes=frozenset(f"ns:{ns}" for ns in expected_ns),
            delta=ns_delta,
        )
        expose_delta = tuple(("endpoint_exposed", (ep,), 1) for ep in sorted(expected_endpoints))
        expose_step = RoundStep(
            step_id="expose-endpoints",
            priority=1,
            plan_hash=canonical_sha256({"run": run, "step": "expose-endpoints", "endpoints": sorted(expected_endpoints)}),
            writes=frozenset(f"ep-expose:{ep}" for ep in expected_endpoints),
            delta=expose_delta,
        )
        chosen_r1, cert_r1, admitted_r1 = certify_and_select_round(
            archive,
            run=run,
            cut="namespaces",
            event_time=2,
            base_namespaces=set(),
            base_protected=set(),
            base_exposed=set(),
            endpoint_namespaces=endpoint_namespaces,
            candidates=(prepare_ns_step, expose_step),
            width=2,
        )
        if [s.step_id for s in chosen_r1] != ["prepare-namespaces"]:
            raise RuntimeError(f"Round 1 selected unexpected steps: {[s.step_id for s in chosen_r1]}")

        _apply_namespaces_and_default_deny(live, run, topo)
        observed_ns = live.managed_namespaces()
        if set(observed_ns) != set(expected_ns):
            raise RuntimeError(f"Round 1 namespace readback mismatch: {observed_ns} != {expected_ns}")
        boundaries.append(
            live.record_boundary(
                1,
                cut="namespaces",
                managed_namespaces=observed_ns,
                protected_endpoints=[],
                exposed_endpoints=[],
                certificate=cert_r1,
                admitted_round=admitted_r1,
            )
        )

        # Round 2: certify protection before exposure (exposing first or together violates unprotected_exposure).
        protect_delta = tuple(("endpoint_protected", (ep,), 1) for ep in sorted(expected_endpoints))
        protect_step = RoundStep(
            step_id="protect-endpoints",
            priority=0,
            plan_hash=canonical_sha256({"run": run, "step": "protect-endpoints", "endpoints": sorted(expected_endpoints)}),
            writes=frozenset(f"ep-protect:{ep}" for ep in expected_endpoints),
            delta=protect_delta,
        )
        chosen_r2, cert_r2, admitted_r2 = certify_and_select_round(
            archive,
            run=run,
            cut="protected",
            event_time=3,
            base_namespaces=set(observed_ns),
            base_protected=set(),
            base_exposed=set(),
            endpoint_namespaces=endpoint_namespaces,
            candidates=(protect_step, expose_step),
            width=2,
        )
        if [s.step_id for s in chosen_r2] != ["protect-endpoints"]:
            raise RuntimeError(f"Round 2 selected unexpected steps: {[s.step_id for s in chosen_r2]}")

        expected_protections = _expected_protections(run, topo)
        _apply_scoped_protections(live, run, expected_protections)
        admission_check = live.verify_unsigned_admission_denial(topo.unsigned_artifact)
        observed_protected = _read_protected_endpoints(
            live.managed_network_policies(),
            run,
            expected_protections,
        )
        if set(observed_protected) != expected_endpoints:
            raise RuntimeError(f"Round 2 policy readback mismatch: {observed_protected}")
        boundaries.append(
            live.record_boundary(
                2,
                cut="protected",
                managed_namespaces=live.managed_namespaces(),
                protected_endpoints=observed_protected,
                exposed_endpoints=[],
                certificate=cert_r2,
                admitted_round=admitted_r2,
            )
        )

        # Round 3: now that live readback proved protection, certify exposure and verify with probes + Hubble.
        chosen_r3, cert_r3, admitted_r3 = certify_and_select_round(
            archive,
            run=run,
            cut="ready",
            event_time=4,
            base_namespaces=set(observed_ns),
            base_protected=set(observed_protected),
            base_exposed=set(),
            endpoint_namespaces=endpoint_namespaces,
            candidates=(expose_step,),
            width=1,
        )
        if [s.step_id for s in chosen_r3] != ["expose-endpoints"]:
            raise RuntimeError(f"Round 3 selected unexpected steps: {[s.step_id for s in chosen_r3]}")

        pod_ips = _apply_protected_pods(live, run, topo)
        network_cases = _run_network_verification(live, topo, pod_ips)
        observed_exposed = _read_exposed_endpoints(live.managed_pods(), run, topo.endpoint_zones)
        if set(observed_exposed) != expected_endpoints:
            raise RuntimeError(f"Round 3 exposed endpoint readback mismatch: {observed_exposed}")
        boundaries.append(
            live.record_boundary(
                3,
                cut="ready",
                managed_namespaces=live.managed_namespaces(),
                protected_endpoints=observed_protected,
                exposed_endpoints=observed_exposed,
                certificate=cert_r3,
                admitted_round=admitted_r3,
            )
        )

    prohibited_case = next(
        case
        for case in network_cases
        if case["source"] == topo.prohibited_recovery_flow["source"]
        and case["destination"] == topo.prohibited_recovery_flow["destination"]
    )
    findings = [
        {
            "reason": "prohibited-recovery-flow",
            "source": topo.prohibited_recovery_flow["source"],
            "destination": topo.prohibited_recovery_flow["destination"],
            "function": topo.prohibited_recovery_flow["function"],
            "probe": prohibited_case["probe"],
            "hubble_receipt": prohibited_case["hubble_receipt"],
        },
        {
            "reason": "unsigned-component",
            "service": topo.unsigned_artifact["service"],
            "artifact": topo.unsigned_artifact["artifact"],
            "admission": admission_check,
        },
    ]

    return {
        "run": run,
        "outcome": "success",
        "managed_namespaces": live.managed_namespaces(),
        "boundaries": boundaries,
        "findings": findings,
        "network_cases": network_cases,
    }
