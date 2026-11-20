"""A completed inventory can establish absence; a restore identifies one backup."""

from hashlib import sha256

import pytest

from case_support import imported, verified


def records():
    services = ("missing", "old", "kept", "unread")
    return {
        "backup_plan": [{"id": s, "service": s, "dataset": f"{s}-data", "target": "vault",
                         "decided_by": "daily", "interval_days": 1, "retention_days": 14} for s in services],
        "backup_decision": [{"id": "daily", "as_of": "2026-06-10", "max_age_days": 2}],
        "backup_inventory": [{"id": f"scan-{s}", "service": s, "target": "vault", "day": "2026-06-10", "complete": True}
                             for s in services if s != "unread"] + [
            {"id": "other-store", "service": "unread", "target": "elsewhere", "day": "2026-06-10", "complete": True},
            {"id": "yesterday", "service": "unread", "target": "vault", "day": "2026-06-09", "complete": True}],
        "backup_copy": [
            {"id": "older", "service": "old", "target": "vault", "taken": "2026-06-07"},
            {"id": "last", "service": "kept", "target": "vault", "taken": "2026-06-08"},
            {"id": "fresh", "service": "kept", "target": "vault", "taken": "2026-06-09"},
        ],
    }


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: Implement the platform backup-plan, scoped inventory and age rules in schema/management_backup.yaml "
    "and rules/management_backup.dl using std-time and std-decision. Read decisions/platform-management-backup.md. "
    "Waits for boolean support in compiler/tests/souffle.py (TYPE lacks boolean and TRUE/FALSE are not rewritten, "
    "crashing examples/test_rules.py Souffle oracle tests on backup_inventory__complete with KeyError: 'boolean') "
    "and for view_typing.resolve and view_rules.bind to support attributes on multi-source kind unions in views.yaml "
    "(#716 only updated view_rules.lower, and views.yaml already maps std-time reference_point to cluster_right_clock)."))
def test_management_backup_age_and_absence():
    from management_probes import compiled

    data = records()
    for complete in (False, True):
        data["backup_inventory"][0]["complete"] = complete
        model, state = compiled(data)
        expected = {("missing", "missing" if complete else "unknown"), ("old", "too-old"),
                    ("kept", "current"), ("unread", "unknown")}
        assert state.derived.get("managed_backup_state") == expected
        leaves = verified("managed_backup_state", ("old", "too-old"), state=(model, state))
        assert ("backup_copy__taken", ("older", "2026-06-07")) in leaves
        if complete:
            leaves = verified("managed_backup_state", ("missing", "missing"), state=(model, state))
            assert any(rel.startswith("backup_inventory__") and key[0] == "scan-missing" for rel, key in leaves)
    imported("std-time")
    imported("std-decision")


@pytest.mark.parametrize(("kind", "changes"), [
    pytest.param(None, {}, id="matching-capture-and-readback"),
    pytest.param("backup_capture", None, id="missing-capture"),
    pytest.param("backup_readback", None, id="missing-readback"),
    pytest.param("backup_capture", {"backup": "fresh"}, id="different-backup-captured"),
    pytest.param("backup_readback", {"backup": "fresh"}, id="different-backup-read"),
    pytest.param("backup_capture", {"id": "capture-2"}, id="capture-evidence-mismatch"),
    pytest.param("backup_readback", {"id": "capture-1"}, id="reused-observation-id"),
    pytest.param("backup_readback", {"trial": "restore-2"}, id="different-trial"),
    pytest.param("backup_capture", {"run": "other"}, id="capture-from-another-run"),
    pytest.param("backup_readback", {"run": "other"}, id="readback-from-another-run"),
    pytest.param("backup_readback", {"cluster": "elsewhere"}, id="wrong-recovery-cluster"),
    pytest.param("backup_capture", {"source_cluster": "recovery"}, id="same-cluster"),
    pytest.param("backup_readback", {"payload_sha256": sha256(b"other bytes").hexdigest()}, id="different-readback-bytes"),
])
def test_management_restore_matches_copy(kind, changes):
    from management_probes import compiled

    captured_payload = b"fresh backup marker\n"
    recovered_payload = b"fresh backup marker\n"
    capture_digest = sha256(captured_payload).hexdigest()
    readback_digest = sha256(recovered_payload).hexdigest()
    data = {
        "backup_trial": [{"id": "restore-1", "backup": "last", "cluster": "recovery", "run": "trial-run"}],
        "backup_capture": [{"id": "capture-1", "backup": "last", "source_cluster": "work", "run": "trial-run",
                            "payload_sha256": capture_digest}],
        "backup_readback": [{"id": "readback-1", "backup": "last", "cluster": "recovery", "run": "trial-run",
                             "trial": "restore-1", "source_evidence": "capture-1", "payload_sha256": readback_digest}],
    }
    if kind is not None:
        if changes is None:
            data[kind].clear()
        else:
            data[kind][0].update(changes)

    model, state = compiled(data)
    restored = ("last", "restore-1")
    assert state.derived.get("managed_backup_restored") == ({restored} if kind is None else set())
    if kind is None:
        leaves = verified("managed_backup_restored", restored, state=(model, state))
        assert {
            ("backup_trial__backup", ("restore-1", "last")),
            ("backup_capture__backup", ("capture-1", "last")),
            ("backup_capture__payload_sha256", ("capture-1", capture_digest)),
            ("backup_readback__source_evidence", ("readback-1", "capture-1")),
            ("backup_readback__payload_sha256", ("readback-1", readback_digest)),
        } <= leaves


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: Depends on the recorded disposable recovery cluster and test_management_restore_matches_copy. "
    "Restore a fresh marker while management stays down per decisions/platform-management-backup.md."))
def test_management_backup_restore_readback():
    from management_probes import live_events

    events = live_events("backup")
    captured, = [e for e in events if e["kind"] == "backup-completed"]
    readback, = [e for e in events if e["kind"] == "recovered-read"]
    assert captured["backup"] == readback["backup"] and captured["source_cluster"] != readback["cluster"] == "recovery"
    assert captured["payload_sha256"] == readback["payload_sha256"] and len(readback["payload_sha256"]) == 64
    assert readback["source_evidence"] == captured["evidence"]
    boundaries = [e for e in events if e["kind"] == "management-unreachable"]
    assert len(boundaries) >= 2 and events.index(boundaries[0]) < events.index(readback) < events.index(boundaries[-1])
    assert all(e["cluster"] == "management" and e["probe_result"] == "unreachable" for e in boundaries)


def test_management_backup_routes():
    from management_probes import compiled

    data = {"backup_site": [{"id": "work", "function": "producer"}, {"id": "database", "function": "producer"},
                            {"id": "restore", "function": "recovery"}, {"id": "central", "function": "management"}],
            "backup_store": [{"id": "vault", "endpoint": "object-a"}]}
    for target in ("object-a", "object-b"):
        data["backup_store"][0]["endpoint"] = target
        _, state = compiled(data)
        assert state.derived.get("managed_backup_route") == {
            ("work", target, "write"), ("database", target, "write"), ("restore", target, "read")}
