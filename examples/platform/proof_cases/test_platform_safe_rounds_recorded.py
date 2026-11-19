"""Replay authored platform observation cuts and read the resulting public proofs."""

import json
from hashlib import sha256

import pytest
import yaml

from examples.platform.test_tenant_publication_proof import leaves
from rezono_publisher import store
from test_standard_access import checked_publication, copy_pack, role_evidence


QUESTIONS = {"safe-platform-startup": "platform_startup_goal",
             "offline-management-dataset-restore": "platform_restore_goal"}


def observe(run, cut, subject, attribute, value, evidence):
    return {"id": evidence, "run": run, "cut": cut, "subject": subject, "attribute": attribute, "value": value}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: Depends on test_startup_transition_cases, test_restore_offline_dependencies and test_certified_round_replay. "
    "Bind platform steps to certified rounds and publish startup and isolated management dataset restore reader "
    "questions and their actual goal witnesses per decisions/safe-step-rounds.md, sections 3, 4 and 7."))
def test_platform_safe_rounds_recorded(tmp_path):
    root = copy_pack(tmp_path / "inputs")
    bucket = store.FileStore(tmp_path / "published")
    _, manifest = checked_publication(root, bucket, 1)
    bundle_entry, = [entry for entry in manifest["compiled"] if entry["file"] == "bundle/schema-bundle.json"]
    raw = bucket.get(bundle_entry["uri"].removeprefix(bucket.uri("")))
    assert sha256(raw).hexdigest() == bundle_entry["sha256"]
    bundle = json.loads(raw)
    readers = {row["id"]: row for row in bundle.get("reader_questions", ())}
    assert QUESTIONS.items() <= {(key, row["relation"]) for key, row in readers.items()}, (
        "Missing reader questions for startup and offline restore goal relations")
    proof_terms = {question["term"] for question in bundle["questions"] if question["start"] == "present"}
    assert all(readers[question]["proof"] in proof_terms and readers[question]["columns"] for question in QUESTIONS)

    # These are inputs recorded at the boundary, independently of the dispatch and goal expectations below.
    startup, recovery = "recorded-startup", "recorded-recovery"
    records = {
        "safe_round_cut": [
            {"id": "empty", "run": startup},
            {"id": "protected", "run": startup, "previous": "empty"},
            {"id": "ready", "run": startup, "previous": "protected"},
            {"id": "offline", "run": recovery},
            {"id": "restored", "run": recovery, "previous": "offline"},
        ],
        "safe_step_request": [
            {"id": "protect-entry", "run": startup, "effect": "protect", "subject": "lb"},
            {"id": "expose-entry", "run": startup, "effect": "expose", "subject": "lb"},
            {"id": "restore-copy", "run": recovery, "effect": "restore", "subject": "recovery"},
        ],
        "safe_step_scope": [
            {"id": "empty-fixture", "run": startup, "cut": "empty", "reader": "inventory", "scope": "platform"},
            {"id": "empty-router", "run": startup, "cut": "empty", "reader": "router", "scope": "lb"},
        ],
        "safe_step_observation": [
            observe(startup, "protected", "lb", "network-policy", "effective", "policy-readback"),
            observe(startup, "protected", "lb", "router-policy", "effective", "router-readback"),
            observe(startup, "ready", "lb", "listener", "externally-ready", "entry-readback"),
            observe(startup, "ready", "restore-bad", "network-probe", "denied", "isolation-probe"),
            observe(recovery, "offline", "management", "availability", "unreachable", "opening-offline-probe"),
            observe(recovery, "restored", "management", "availability", "unreachable", "closing-offline-probe"),
        ],
    }
    digest = sha256(b"authored management dataset\n").hexdigest()
    records.update({
        "backup_trial": [{"id": "management-trial", "backup": "management-copy", "cluster": "recovery", "run": recovery}],
        "backup_capture": [{"id": "management-capture", "backup": "management-copy", "source_cluster": "management",
                            "run": recovery, "payload_sha256": digest}],
        "backup_readback": [{"id": "isolated-readback", "backup": "management-copy", "cluster": "recovery", "run": recovery,
                             "trial": "management-trial", "source_evidence": "management-capture", "payload_sha256": digest}],
        "restore_dependency_binding": [
            {"id": "local-api-binding", "trial": "management-trial", "function": "control", "provider": "recovery-api", "cluster": "recovery"},
            {"id": "local-key-binding", "trial": "management-trial", "function": "credentials", "provider": "recovery-key", "cluster": "recovery"},
            {"id": "direct-store-binding", "trial": "management-trial", "function": "storage", "provider": "backup-store", "cluster": "storage"},
        ],
        "restore_dependency_reading": [
            {"id": "local-control-readback", "trial": "management-trial", "run": recovery, "provider": "recovery-api", "cluster": "recovery", "value": "available"},
            {"id": "local-key-readback", "trial": "management-trial", "run": recovery, "provider": "recovery-key", "cluster": "recovery", "value": "available"},
            {"id": "direct-store-readback", "trial": "management-trial", "run": recovery, "provider": "backup-store", "cluster": "storage", "value": "available"},
        ],
        "restore_dataset_binding": [{"id": "catalog-copy", "trial": "management-trial", "dataset": "management-catalog",
                                     "backup": "management-copy", "capture": "management-capture"}],
        "restore_offline_interval": [{"id": "complete-fence-history", "run": recovery, "trial": "management-trial",
                                      "start_evidence": "opening-offline-probe", "end_evidence": "closing-offline-probe",
                                      "readback_evidence": "isolated-readback"}],
    })
    recording = root / "facts" / "safe-rounds-recording.yaml"
    recording.write_text(yaml.safe_dump(records), encoding="utf-8")
    publication = checked_publication(root, bucket, 2)
    rows, witnesses = role_evidence(bucket, publication, "checker")

    actual = {row for row in rows if row[0] == "platform_safe_frontier" and row[1][0] in {startup, recovery}}
    assert actual == {("platform_safe_frontier", (startup, "empty", "protect-entry")),
                      ("platform_safe_frontier", (startup, "protected", "expose-entry")),
                      ("platform_safe_frontier", (recovery, "offline", "restore-copy"))}
    frontier_grounds = {
        (startup, "empty", "protect-entry"): {("safe_step_scope__scope", ("empty-fixture", "platform"))},
        (startup, "protected", "expose-entry"): {
            ("safe_step_observation__value", ("policy-readback", "effective")),
            ("safe_step_observation__value", ("router-readback", "effective")),
        },
        (recovery, "offline", "restore-copy"): {
            ("safe_step_observation__value", ("opening-offline-probe", "unreachable")),
            ("restore_dependency_reading__value", ("local-control-readback", "available")),
            ("restore_dependency_reading__value", ("local-key-readback", "available")),
            ("restore_dependency_reading__value", ("direct-store-readback", "available")),
        },
    }
    assert actual <= witnesses.keys()
    for head in actual:
        run, cut, step = head[1]
        assert frontier_grounds[head[1]] | {("safe_round_cut__run", (cut, run))} <= leaves(witnesses, head)
        assert any(relation == "ready" and key[:2] == (run, step) for relation, key in witnesses[head])
    protect_first = ("platform_safe_blocker", (startup, "empty", "expose-entry", "unprotected-listener"))
    assert protect_first in witnesses
    assert ("safe_step_scope__scope", ("empty-router", "lb")) in leaves(witnesses, protect_first)

    startup_goal = (QUESTIONS["safe-platform-startup"], (startup, "ready", "platform", "observed-ready"))
    recovery_goal = (QUESTIONS["offline-management-dataset-restore"],
                     (recovery, "restored", "management-catalog", "isolated-readback"))
    assert {startup_goal, recovery_goal} <= rows & witnesses.keys()
    assert {("recovery_reaches_out", ("restore-bad", "idp", "identity")),
            ("unverified_supply", ("lab",))} <= rows
    assert {("safe_step_observation__value", ("entry-readback", "externally-ready")),
            ("safe_step_observation__value", ("isolation-probe", "denied"))} <= leaves(witnesses, startup_goal)
    assert {("backup_readback__payload_sha256", ("isolated-readback", digest)),
            ("restore_dataset_binding__dataset", ("catalog-copy", "management-catalog")),
            ("restore_offline_interval", ("complete-fence-history",))} <= leaves(witnesses, recovery_goal)

    # An isolated readback and two unreachable probes still do not prove the full interval.
    records["restore_offline_interval"] = []
    recording.write_text(yaml.safe_dump(records), encoding="utf-8")
    partial = checked_publication(root, bucket, 3)
    rows, witnesses = role_evidence(bucket, partial, "checker")
    assert startup_goal in rows & witnesses.keys()
    assert recovery_goal not in rows and recovery_goal not in witnesses
