"""Replay authored platform observation cuts as std-loop rows with admitted Evidence and read the public proofs."""

from copy import deepcopy
from hashlib import sha256
import json

import pytest
import yaml

from examples.platform.test_tenant_publication_proof import leaves
from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_checker.evidence import Evidence, admit
from rezono_checker.transition import check_transition_certificate
from rezono_publisher import batch, publish, store
from test_standard_access import ROLES, copy_pack, role_evidence


QUESTIONS = {"safe-platform-startup": "platform_startup_goal",
             "offline-management-dataset-restore": "platform_restore_goal"}
STARTUP_MANIFEST = "desired-platform-startup"
RECOVERY_MANIFEST = "desired-platform-recovery"
STARTUP_INVARIANTS = ("unprotected_listener",)
RECOVERY_INVARIANTS = ("online_management_restore",)


def _relation(name, role, columns, *, invariant=False):
    signature = {"name": name, "role": role, "key": [{"name": column, "type": "string"} for column in columns]}
    return {**signature, "invariant": True} if invariant else signature


def _literal(relation, *terms, negative=False):
    return {"relation": relation, "terms": list(terms),
            "polarity": "negative" if negative else "positive", "stratum": "0"}


def _rule(name, head, body, *, stratum="0"):
    return {"id": name, "stratum": stratum, "head": {"relation": name, "terms": list(head)}, "body": body}


def _row(relation, cells):
    return {"relation": relation, "key": canonical_json(list(cells))}


STARTUP_PROGRAM = {
    "format": "rezono.rules/1",
    "relations": [
        _relation("lb_policy", "base", ("subject", "status")),
        _relation("lb_exposed", "base", ("subject",)),
        _relation("lb_protected", "derived", ("subject",)),
        _relation("unprotected_listener", "derived", ("subject",), invariant=True),
    ],
    "rules": [
        _rule("lb_protected", ("?subject",), [_literal("lb_policy", "?subject", "effective")]),
        _rule("unprotected_listener", ("?subject",), [
            _literal("lb_exposed", "?subject"),
            _literal("lb_protected", "?subject", negative=True),
        ], stratum="1"),
    ],
}

RECOVERY_PROGRAM = {
    "format": "rezono.rules/1",
    "relations": [
        _relation("recovery_plane", "base", ("cluster", "state")),
        _relation("recovery_restore", "base", ("trial", "state")),
        _relation("management_offline", "derived", ("cluster",)),
        _relation("online_management_restore", "derived", ("trial",), invariant=True),
    ],
    "rules": [
        _rule("management_offline", ("?cluster",), [_literal("recovery_plane", "?cluster", "unreachable")]),
        _rule("online_management_restore", ("?trial",), [
            _literal("recovery_restore", "?trial", "restored"),
            _literal("management_offline", "management", negative=True),
        ], stratum="1"),
    ],
}


def observe(run, cut, evidence, reader, token, value, *, time, state="known"):
    return {"id": evidence, "run": run, "token": token, "event_time": time, "state": state, "value": value,
            "reason": evidence, "scope": reader, "sweep": cut}


def _publish(pack, bucket, number, *, evidence=None):
    epoch = batch.epoch(pack, epoch=number, knowledge_time=f"2026-01-{number:02d}T00:00:00Z",
                        sources=[("rules", "safe-rounds-test")], evidence=evidence)
    manifest = publish.publish(epoch, bucket, ROLES)
    return epoch, manifest


def _startup_snapshot(label, policy, *, exposed=False):
    protected = [("lb",)] if policy == "effective" else []
    exposed_rows = [("lb",)] if exposed else []
    violated = [("lb",)] if exposed and policy != "effective" else []
    witnesses = []
    if protected:
        witnesses.append({
            "rule_id": "lb_protected",
            "conclusion": _row("lb_protected", ("lb",)),
            "bindings": [{"variable": "?subject", "value": "lb"}],
            "premises": [{"row": _row("lb_policy", ("lb", "effective")), "polarity": "positive", "stratum": 0}],
        })
    if violated:
        witnesses.append({
            "rule_id": "unprotected_listener",
            "conclusion": _row("unprotected_listener", ("lb",)),
            "bindings": [{"variable": "?subject", "value": "lb"}],
            "premises": [
                {"row": _row("lb_exposed", ("lb",)), "polarity": "positive", "stratum": 0},
                {"row": _row("lb_protected", ("lb",)), "polarity": "negative", "stratum": 0},
            ],
        })
    return {
        "id": label,
        "rows": {
            "lb_policy": [("lb", policy)],
            "lb_exposed": exposed_rows,
            "lb_protected": protected,
            "unprotected_listener": violated,
        },
        "witnesses": witnesses,
    }


def _recovery_snapshot(label, state):
    return {
        "id": label,
        "rows": {
            "recovery_plane": [("management", "unreachable"), ("recovery", "available")],
            "recovery_restore": [("management-trial", state)],
            "management_offline": [("management",)],
            "online_management_restore": [],
        },
        "witnesses": [{
            "rule_id": "management_offline",
            "conclusion": _row("management_offline", ("management",)),
            "bindings": [{"variable": "?cluster", "value": "management"}],
            "premises": [{"row": _row("recovery_plane", ("management", "unreachable")),
                          "polarity": "positive", "stratum": 0}],
        }],
    }


def _certificate(manifest, program, invariants, run, cut, base, variant, *,
                 rule, bindings, effects, expected_old, delta):
    return {
        "manifest": manifest,
        "definition_sha256": canonical_sha256(program),
        "run": run,
        "cut": cut,
        "base": canonical_sha256(base),
        "variant": canonical_sha256(variant),
        "rule": rule,
        "bindings": bindings,
        "effect": canonical_sha256(list(effects)),
        "expected_old": expected_old,
        "delta": delta,
        "invariants": {name: {"rows": [], "count": "0"} for name in invariants},
    }


def _archive_bundle(archive_dir):
    archive = store.FileStore(archive_dir)

    def put(group, name, body):
        data = body if isinstance(body, bytes) else canonical_bytes(body)
        file = f"observations/{group}/{name}.json"
        archive.put_new(file, data)
        return {"file": file, "uri": f"s3://rezono/{file}", "sha256": sha256_hex(data)}

    def build(context, index):
        trusted = put("retained", "context", {"completeness": [], "rounds": []} | context)
        candidates = put("submitted", "index", {"completeness_receipts": [], "rounds": []} | index)
        return Evidence(trusted, candidates, lambda uri: archive.get(uri.removeprefix(archive.uri(""))))

    return put, build


def _sweep_receipt(put, tag, scope, report):
    """Pin one trusted completeness authority and one submitted receipt for a single-node scope."""
    member = ["sweep-node", scope["run"], scope["collector"], scope["window"], report["node"]]
    source = {"kind": "tool", "name": f"{scope['collector']}-observer", "position": f"{scope['window']}/10"}
    authorization = put("retained", f"{tag}-authority", {"issuer": source["name"], "scope": scope})
    definition = put("retained", f"{tag}-definition", {"query": "expected-sweep-nodes", "scope": scope})
    inventory = [member]
    content = [{
        "key": member,
        "terminal": {**source, "position": f"final/{report['node']}"},
        "rows": [{"key": [report["id"]], "values": report, "source": {**source, "position": report["id"]}}],
    }]
    common = {
        "source": source,
        "issuer": {"id": source["name"], "authorization": authorization},
        "scope": {
            "definition": definition,
            "query": "expected-sweep-nodes",
            "bindings": [{"name": k, "type": "string", "value": v} for k, v in scope.items()],
        },
        "cut": {"frontier": {"source_id": source["name"], "position": "10"}},
    }
    trusted = {
        **common,
        "inventory": put("retained", f"{tag}-inventory", inventory),
        "content": put("retained", f"{tag}-content", content),
    }
    submitted = {
        **common,
        "inventory": put("submitted", f"{tag}-inventory", inventory),
        "content": put("submitted", f"{tag}-content", content),
    }
    receipt = put("submitted", f"{tag}-receipt",
                  {"id": canonical_sha256(["rezono.completeness-receipt/1", submitted]), **submitted})
    return trusted, receipt


def _opening_evidence(archive_dir, startup, recovery, scope_reports):
    """Real Evidence bundle for the opening cuts: two scoped completeness receipts and two certified rounds.

    At startup's empty cut (width 2), the round verifier refutes [protect-entry, expose-entry] using the
    real unprotected_listener violation on its visible expose-first boundary and admits [protect-entry].
    At recovery's offline cut (width 1), the round verifier admits [restore-copy].
    """
    put, build = _archive_bundle(archive_dir)
    authorities, receipts = [], []
    for tag, scope, report in scope_reports:
        authority, receipt = _sweep_receipt(put, tag, scope, report)
        authorities.append(authority)
        receipts.append(receipt)

    # Startup empty cut: protect-entry is safe; expose-entry before protect-entry violates unprotected_listener.
    protect_delta = [("lb_policy", ("lb", "none"), -1), ("lb_policy", ("lb", "effective"), 1)]
    expose_delta = [("lb_exposed", ("lb",), 1)]
    protect_hash = canonical_sha256({"step": "protect-entry", "subject": "lb", "delta": protect_delta})
    expose_hash = canonical_sha256({"step": "expose-entry", "subject": "lb", "delta": expose_delta})
    startup_obs = canonical_bytes({"id": "read-empty", "run": startup, "scope": "platform", "cut": "empty"})
    startup_cut = {"id": "empty", "run": startup, "scope": "platform", "observation_sha256": sha256_hex(startup_obs)}
    startup_base = _startup_snapshot("startup-empty-base", "none", exposed=False)
    protect_variant = _startup_snapshot("startup-protected-variant", "effective", exposed=False)
    expose_variant = _startup_snapshot("startup-exposed-unprotected-variant", "none", exposed=True)

    protect_cert = _certificate(
        STARTUP_MANIFEST, STARTUP_PROGRAM, STARTUP_INVARIANTS, startup, "empty", startup_base, protect_variant,
        rule="protect-entry", bindings={"subject": "lb"}, effects=[protect_hash],
        expected_old=[_row("lb_policy", ("lb", "none"))], delta=protect_delta,
    )
    expose_violation_cert = _certificate(
        STARTUP_MANIFEST, STARTUP_PROGRAM, STARTUP_INVARIANTS, startup, "empty", startup_base, expose_variant,
        rule="expose-entry", bindings={"subject": "lb"}, effects=[expose_hash],
        expected_old=[], delta=expose_delta,
    )
    startup_ctx = {
        "manifest": STARTUP_MANIFEST, "definition_sha256": canonical_sha256(STARTUP_PROGRAM),
        "program": STARTUP_PROGRAM, "invariants": STARTUP_INVARIANTS,
        "cut": startup_cut, "observations": {"read-empty": startup_obs},
    }
    assert check_transition_certificate(protect_cert, startup_ctx, startup_base, protect_variant) == {
        "valid": True, "findings": [],
    }
    violation = check_transition_certificate(expose_violation_cert, startup_ctx, startup_base, expose_variant)
    assert not violation["valid"] and any(
        f.get("snapshot") == "variant" and f["reason"] == "invariant_violated" for f in violation["findings"]
    )

    startup_round_ctx = {
        "run": startup, "cut": startup_cut, "manifest": STARTUP_MANIFEST,
        "definition_sha256": canonical_sha256(STARTUP_PROGRAM),
        "program": put("retained", "startup-program", STARTUP_PROGRAM),
        "invariants": list(STARTUP_INVARIANTS),
        "observations": {"read-empty": put("retained", "startup-empty-obs", startup_obs)},
        "base": put("retained", "startup-empty-base", startup_base),
        "domain": put("retained", "startup-empty-domain", {
            "width": 2,
            "steps": [
                {"step": "protect-entry", "priority": 0, "effects": [protect_hash]},
                {"step": "expose-entry", "priority": 1, "effects": [expose_hash]},
            ],
        }),
    }
    startup_claim = put("submitted", "claim-protect-entry", {
        "run": startup, "cut": "empty", "batch": "batch-protect-entry", "members": ["protect-entry"],
        "subsets": [
            {
                "members": ["protect-entry"], "effects": [protect_hash],
                "variant": put("submitted", "variant-protect-entry", protect_variant),
                "certificate": put("submitted", "cert-protect-entry", protect_cert),
            },
            {
                "members": ["expose-entry"], "effects": [expose_hash],
                "variant": put("submitted", "variant-expose-unprotected", expose_variant),
                "certificate": put("submitted", "cert-expose-unprotected", expose_violation_cert),
            },
        ],
    })

    # Recovery offline cut: management is unreachable and restore-copy is safe alone.
    restore_delta = [("recovery_restore", ("management-trial", "pending"), -1),
                     ("recovery_restore", ("management-trial", "restored"), 1)]
    restore_hash = canonical_sha256({"step": "restore-copy", "trial": "management-trial", "delta": restore_delta})
    recovery_obs = canonical_bytes({"id": "read-offline", "run": recovery, "scope": "recovery", "cut": "offline"})
    recovery_cut = {"id": "offline", "run": recovery, "scope": "recovery",
                    "observation_sha256": sha256_hex(recovery_obs)}
    recovery_base = _recovery_snapshot("recovery-offline-base", "pending")
    recovery_variant = _recovery_snapshot("recovery-restored-variant", "restored")
    restore_cert = _certificate(
        RECOVERY_MANIFEST, RECOVERY_PROGRAM, RECOVERY_INVARIANTS, recovery, "offline", recovery_base, recovery_variant,
        rule="restore-copy", bindings={"trial": "management-trial"}, effects=[restore_hash],
        expected_old=[_row("recovery_restore", ("management-trial", "pending"))], delta=restore_delta,
    )
    recovery_ctx = {
        "manifest": RECOVERY_MANIFEST, "definition_sha256": canonical_sha256(RECOVERY_PROGRAM),
        "program": RECOVERY_PROGRAM, "invariants": RECOVERY_INVARIANTS,
        "cut": recovery_cut, "observations": {"read-offline": recovery_obs},
    }
    assert check_transition_certificate(restore_cert, recovery_ctx, recovery_base, recovery_variant) == {
        "valid": True, "findings": [],
    }

    recovery_round_ctx = {
        "run": recovery, "cut": recovery_cut, "manifest": RECOVERY_MANIFEST,
        "definition_sha256": canonical_sha256(RECOVERY_PROGRAM),
        "program": put("retained", "recovery-program", RECOVERY_PROGRAM),
        "invariants": list(RECOVERY_INVARIANTS),
        "observations": {"read-offline": put("retained", "recovery-offline-obs", recovery_obs)},
        "base": put("retained", "recovery-offline-base", recovery_base),
        "domain": put("retained", "recovery-offline-domain", {
            "width": 1,
            "steps": [{"step": "restore-copy", "priority": 0, "effects": [restore_hash]}],
        }),
    }
    recovery_claim = put("submitted", "claim-restore-copy", {
        "run": recovery, "cut": "offline", "batch": "batch-restore-copy", "members": ["restore-copy"],
        "subsets": [{
            "members": ["restore-copy"], "effects": [restore_hash],
            "variant": put("submitted", "variant-restore-copy", recovery_variant),
            "certificate": put("submitted", "cert-restore-copy", restore_cert),
        }],
    })

    evidence = build(
        {"completeness": authorities, "rounds": [startup_round_ctx, recovery_round_ctx]},
        {"completeness_receipts": receipts, "rounds": [startup_claim, recovery_claim]},
    )
    admitted = admit(evidence)
    assert admitted.findings == []
    assert set(admitted.rows["verified_round"]) == {
        (startup_claim["sha256"], startup, "empty", "batch-protect-entry"),
        (recovery_claim["sha256"], recovery, "offline", "batch-restore-copy"),
    }
    assert set(admitted.rows["verified_round_member"]) == {
        (startup_claim["sha256"], "protect-entry"),
        (recovery_claim["sha256"], "restore-copy"),
    }
    return evidence


def _protected_evidence(archive_dir, startup):
    """Real Evidence bundle for startup's protected cut: expose-entry is now safe with protection observed."""
    put, build = _archive_bundle(archive_dir)
    expose_delta = [("lb_exposed", ("lb",), 1)]
    expose_hash = canonical_sha256({"step": "expose-entry", "subject": "lb", "delta": expose_delta})
    obs = canonical_bytes({"id": "read-protected", "run": startup, "scope": "platform", "cut": "protected"})
    cut = {"id": "protected", "run": startup, "scope": "platform", "observation_sha256": sha256_hex(obs)}
    base = _startup_snapshot("startup-protected-base", "effective", exposed=False)
    variant = _startup_snapshot("startup-exposed-variant", "effective", exposed=True)
    cert = _certificate(
        STARTUP_MANIFEST, STARTUP_PROGRAM, STARTUP_INVARIANTS, startup, "protected", base, variant,
        rule="expose-entry", bindings={"subject": "lb"}, effects=[expose_hash],
        expected_old=[], delta=expose_delta,
    )
    ctx = {
        "manifest": STARTUP_MANIFEST, "definition_sha256": canonical_sha256(STARTUP_PROGRAM),
        "program": STARTUP_PROGRAM, "invariants": STARTUP_INVARIANTS,
        "cut": cut, "observations": {"read-protected": obs},
    }
    assert check_transition_certificate(cert, ctx, base, variant) == {"valid": True, "findings": []}

    round_ctx = {
        "run": startup, "cut": cut, "manifest": STARTUP_MANIFEST,
        "definition_sha256": canonical_sha256(STARTUP_PROGRAM),
        "program": put("retained", "startup-program", STARTUP_PROGRAM),
        "invariants": list(STARTUP_INVARIANTS),
        "observations": {"read-protected": put("retained", "startup-protected-obs", obs)},
        "base": put("retained", "startup-protected-base", base),
        "domain": put("retained", "startup-protected-domain", {
            "width": 1,
            "steps": [{"step": "expose-entry", "priority": 0, "effects": [expose_hash]}],
        }),
    }
    claim = put("submitted", "claim-expose-entry", {
        "run": startup, "cut": "protected", "batch": "batch-expose-entry", "members": ["expose-entry"],
        "subsets": [{
            "members": ["expose-entry"], "effects": [expose_hash],
            "variant": put("submitted", "variant-expose-entry", variant),
            "certificate": put("submitted", "cert-expose-entry", cert),
        }],
    })
    evidence = build({"rounds": [round_ctx]}, {"rounds": [claim]})
    admitted = admit(evidence)
    assert admitted.findings == []
    assert admitted.rows["verified_round"] == [(claim["sha256"], startup, "protected", "batch-expose-entry")]
    assert admitted.rows["verified_round_member"] == [(claim["sha256"], "expose-entry")]
    return evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: Depends on test_startup_transition_cases, test_restore_offline_dependencies and test_certified_round_replay. "
    "Bind platform steps to std-loop certified rounds and scoped completeness receipts, add the restore dataset "
    "binding and offline interval schema/rules, and publish startup and isolated management dataset restore reader "
    "questions and their actual goal witnesses per decisions/safe-step-rounds.md, sections 3, 4 and 7, "
    "decisions/standard-packs-everywhere.md, section 2.2, and decisions/loop-certificate-admission.md."))
def test_platform_safe_rounds_recorded(tmp_path):
    root = copy_pack(tmp_path / "inputs")
    bucket = store.FileStore(tmp_path / "published")
    _, manifest = _publish(root, bucket, 1)
    bundle_entry, = [entry for entry in manifest["compiled"] if entry["file"] == "bundle/schema-bundle.json"]
    raw = bucket.get(bundle_entry["uri"].removeprefix(bucket.uri("")))
    assert sha256(raw).hexdigest() == bundle_entry["sha256"]
    bundle = json.loads(raw)
    readers = {row["id"]: row for row in bundle.get("reader_questions", ())}
    assert QUESTIONS.items() <= {(key, row["relation"]) for key, row in readers.items()}, (
        "Missing reader questions for startup and offline restore goal relations")
    proof_terms = {question["term"] for question in bundle["questions"] if question["start"] == "present"}
    assert all(readers[question]["proof"] in proof_terms and readers[question]["columns"] for question in QUESTIONS)

    # Opening cuts: startup at empty (t=10) and recovery at offline (t=10), encoded as std-loop rows.
    startup, recovery = "recorded-startup", "recorded-recovery"
    digest = sha256(b"authored management dataset\n").hexdigest()
    empty_fixture_scope = {"run": startup, "collector": "inventory", "window": "empty"}
    empty_router_scope = {"run": startup, "collector": "router", "window": "empty"}
    empty_fixture_report = {**empty_fixture_scope, "id": "empty-fixture-report", "node": "platform",
                            "first": 0, "last": 10, "gaps": 0, "lost": 0}
    empty_router_report = {**empty_router_scope, "id": "empty-router-report", "node": "lb",
                           "first": 0, "last": 10, "gaps": 0, "lost": 0}
    records = {
        "loop_active_run": [{"id": startup}, {"id": recovery}],
        "loop_sweep_receipt": [
            {"id": "empty", "run": startup, "event_time": 10},
            {"id": "offline", "run": recovery, "event_time": 10},
        ],
        "loop_step": [
            {"id": "protect-entry", "precedes": ["expose-entry"]},
            {"id": "expose-entry"},
            {"id": "restore-copy"},
        ],
        "loop_requirement": [
            {"id": "expose-needs-policy", "run": startup, "step": "expose-entry",
             "token": "lb/network-policy", "reason": "effective-protection"},
            {"id": "expose-needs-router", "run": startup, "step": "expose-entry",
             "token": "lb/router-policy", "reason": "effective-protection"},
            {"id": "restore-needs-outage", "run": recovery, "step": "restore-copy",
             "token": "management/availability", "reason": "management-offline"},
            {"id": "restore-needs-control", "run": recovery, "step": "restore-copy",
             "token": "recovery-api/availability", "reason": "control"},
            {"id": "restore-needs-credentials", "run": recovery, "step": "restore-copy",
             "token": "recovery-key/availability", "reason": "credentials"},
            {"id": "restore-needs-storage", "run": recovery, "step": "restore-copy",
             "token": "backup-store/availability", "reason": "storage"},
        ],
        "loop_completion": [
            {"id": "protect-entry-done", "run": startup, "step": "protect-entry",
             "token": "lb/network-policy", "reason": "effective-protection"},
            {"id": "expose-entry-done", "run": startup, "step": "expose-entry",
             "token": "lb/listener", "reason": "observed-ready"},
            {"id": "restore-copy-done", "run": recovery, "step": "restore-copy",
             "token": "management-copy/payload", "reason": "matching-copy"},
        ],
        "loop_expectation": [
            {"id": "lb/network-policy", "value": "effective"},
            {"id": "lb/router-policy", "value": "effective"},
            {"id": "lb/listener", "value": "externally-ready"},
            {"id": "restore-bad/network-probe", "value": "denied"},
            {"id": "management/availability", "value": "unreachable"},
            {"id": "recovery-api/availability", "value": "available"},
            {"id": "recovery-key/availability", "value": "available"},
            {"id": "backup-store/availability", "value": "available"},
            {"id": "management-copy/payload", "value": digest},
        ],
        "flow_sweep_window": [
            {**empty_fixture_scope, "id": "empty-fixture", "start": 0, "stop": 10},
            {**empty_router_scope, "id": "empty-router", "start": 0, "stop": 10},
        ],
        "flow_expected_node": [
            {**empty_fixture_scope, "id": "empty-fixture-platform", "node": "platform"},
            {**empty_router_scope, "id": "empty-router-lb", "node": "lb"},
        ],
        "flow_node_report": [empty_fixture_report, empty_router_report],
        "loop_observation": [
            observe(startup, "empty", "empty-scope-absent", "inventory", "platform/managed-scope", "empty",
                    time=9, state="absent"),
            observe(startup, "empty", "empty-router-absent", "router", "lb/router-policy", "missing",
                    time=9, state="absent"),
            observe(recovery, "offline", "opening-offline-probe", "outage", "management/availability",
                    "unreachable", time=9),
            observe(recovery, "offline", "local-control-readback", "control", "recovery-api/availability",
                    "available", time=9),
            observe(recovery, "offline", "local-key-readback", "credentials", "recovery-key/availability",
                    "available", time=9),
            observe(recovery, "offline", "direct-store-readback", "storage", "backup-store/availability",
                    "available", time=9),
        ],
        "loop_step_safety_check": [
            {"id": "expose-unprotected-at-empty", "run": startup, "step": "expose-entry", "cut": "empty",
             "obligation": "unprotected-listener", "verdict": "refuted", "reason": "violated-invariant"},
        ],
        "backup_trial": [{"id": "management-trial", "backup": "management-copy", "cluster": "recovery", "run": recovery}],
        "backup_capture": [{"id": "management-capture", "backup": "management-copy", "source_cluster": "management",
                            "run": recovery, "payload_sha256": digest}],
        "restore_dependency_binding": [
            {"id": "local-api-binding", "trial": "management-trial", "function": "control",
             "provider": "recovery-api", "cluster": "recovery"},
            {"id": "local-key-binding", "trial": "management-trial", "function": "credentials",
             "provider": "recovery-key", "cluster": "recovery"},
            {"id": "direct-store-binding", "trial": "management-trial", "function": "storage",
             "provider": "backup-store", "cluster": "storage"},
        ],
        "restore_dataset_binding": [{"id": "catalog-copy", "trial": "management-trial",
                                     "dataset": "management-catalog", "backup": "management-copy",
                                     "capture": "management-capture"}],
    }
    recording = root / "facts" / "safe-rounds-recording.yaml"
    recording.write_text(yaml.safe_dump(records), encoding="utf-8")

    # Without admitted round Evidence, no platform step enters the safe frontier.
    unverified = _publish(root, bucket, 2)
    rows, _ = role_evidence(bucket, unverified, "checker")
    assert not {row for row in rows if row[0] == "platform_safe_frontier" and row[1][0] in {startup, recovery}}

    # With admitted completeness receipts and certified rounds, protect-entry and restore-copy are ready.
    opening_evidence = _opening_evidence(tmp_path / "archive-opening", startup, recovery, [
        ("empty-fixture", empty_fixture_scope, empty_fixture_report),
        ("empty-router", empty_router_scope, empty_router_report),
    ])
    opening = _publish(root, bucket, 3, evidence=opening_evidence)
    rows, witnesses = role_evidence(bucket, opening, "checker")

    actual = {row for row in rows if row[0] == "platform_safe_frontier" and row[1][0] in {startup, recovery}}
    assert actual == {("platform_safe_frontier", (startup, "empty", "protect-entry")),
                      ("platform_safe_frontier", (recovery, "offline", "restore-copy"))}
    opening_grounds = {
        (startup, "empty", "protect-entry"): {("flow_node_report__node", ("empty-fixture-report", "platform"))},
        (recovery, "offline", "restore-copy"): {
            ("loop_observation__value", ("opening-offline-probe", "unreachable")),
            ("loop_observation__value", ("local-control-readback", "available")),
            ("loop_observation__value", ("local-key-readback", "available")),
            ("loop_observation__value", ("direct-store-readback", "available")),
        },
    }
    assert actual <= witnesses.keys()
    for head in actual:
        run, cut, step = head[1]
        assert opening_grounds[head[1]] | {("loop_sweep_receipt__run", (cut, run))} <= leaves(witnesses, head)
        assert any(relation == "ready" and key[:2] == (run, step) for relation, key in witnesses[head])
    protect_first = ("platform_safe_blocker", (startup, "empty", "expose-entry", "unprotected-listener"))
    assert protect_first in witnesses
    assert ("flow_node_report__node", ("empty-router-report", "lb")) in leaves(witnesses, protect_first)

    # Next cuts: protection observed at startup's protected cut (t=20), isolated readback at recovery's restored cut.
    records = deepcopy(records)
    records["loop_sweep_receipt"].extend([
        {"id": "protected", "run": startup, "event_time": 20},
        {"id": "restored", "run": recovery, "event_time": 20},
    ])
    records["loop_observation"].extend([
        observe(startup, "protected", "policy-readback", "policy", "lb/network-policy", "effective", time=19),
        observe(startup, "protected", "router-readback", "router", "lb/router-policy", "effective", time=19),
        observe(recovery, "restored", "isolated-readback", "recovery", "management-copy/payload", digest, time=19),
        observe(recovery, "restored", "closing-offline-probe", "outage", "management/availability",
                "unreachable", time=19),
    ])
    records["backup_readback"] = [{"id": "isolated-readback", "backup": "management-copy", "cluster": "recovery",
                                   "run": recovery, "trial": "management-trial",
                                   "source_evidence": "management-capture", "payload_sha256": digest}]
    records["restore_offline_interval"] = [{"id": "complete-fence-history", "run": recovery,
                                            "trial": "management-trial", "start_evidence": "opening-offline-probe",
                                            "end_evidence": "closing-offline-probe",
                                            "readback_evidence": "isolated-readback"}]
    recording.write_text(yaml.safe_dump(records), encoding="utf-8")

    protected_evidence = _protected_evidence(tmp_path / "archive-protected", startup)
    protected = _publish(root, bucket, 4, evidence=protected_evidence)
    rows, witnesses = role_evidence(bucket, protected, "checker")

    expose_head = ("platform_safe_frontier", (startup, "protected", "expose-entry"))
    actual = {row for row in rows if row[0] == "platform_safe_frontier" and row[1][0] in {startup, recovery}}
    assert actual == {expose_head}
    assert expose_head in witnesses
    assert {
        ("loop_sweep_receipt__run", ("protected", startup)),
        ("loop_observation__value", ("policy-readback", "effective")),
        ("loop_observation__value", ("router-readback", "effective")),
    } <= leaves(witnesses, expose_head)
    assert any(relation == "ready" and key[:2] == (startup, "expose-entry") for relation, key in witnesses[expose_head])

    startup_goal = (QUESTIONS["safe-platform-startup"], (startup, "ready", "platform", "observed-ready"))
    recovery_goal = (QUESTIONS["offline-management-dataset-restore"],
                     (recovery, "restored", "management-catalog", "isolated-readback"))
    assert recovery_goal in rows & witnesses.keys()
    assert startup_goal not in rows

    # Final startup cut: listener externally ready and deliberate recovery-isolation probe denied.
    records = deepcopy(records)
    records["loop_sweep_receipt"].append({"id": "ready", "run": startup, "event_time": 30})
    records["loop_observation"].extend([
        observe(startup, "ready", "entry-readback", "entry", "lb/listener", "externally-ready", time=29),
        observe(startup, "ready", "isolation-probe", "network", "restore-bad/network-probe", "denied", time=29),
    ])
    recording.write_text(yaml.safe_dump(records), encoding="utf-8")

    completed = _publish(root, bucket, 5)
    rows, witnesses = role_evidence(bucket, completed, "checker")
    assert {startup_goal, recovery_goal} <= rows & witnesses.keys()
    assert {("recovery_reaches_out", ("restore-bad", "idp", "identity")),
            ("unverified_supply", ("lab",))} <= rows
    assert {("loop_observation__value", ("entry-readback", "externally-ready")),
            ("loop_observation__value", ("isolation-probe", "denied"))} <= leaves(witnesses, startup_goal)
    assert {("backup_readback__payload_sha256", ("isolated-readback", digest)),
            ("restore_dataset_binding__dataset", ("catalog-copy", "management-catalog")),
            ("restore_offline_interval", ("complete-fence-history",))} <= leaves(witnesses, recovery_goal)

    # An isolated readback and two unreachable probes still do not prove the full interval.
    records["restore_offline_interval"] = []
    recording.write_text(yaml.safe_dump(records), encoding="utf-8")
    partial = _publish(root, bucket, 6)
    rows, witnesses = role_evidence(bucket, partial, "checker")
    assert startup_goal in rows & witnesses.keys()
    assert recovery_goal not in rows and recovery_goal not in witnesses
