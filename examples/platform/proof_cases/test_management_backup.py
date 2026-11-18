"""A completed inventory can establish absence; a restore identifies one backup."""

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
        "backup_trial": [{"id": "restore-1", "backup": "last", "cluster": "recovery", "result": "restored",
                          "management": "offline", "before_hash": "a" * 64, "restored_hash": "a" * 64}],
    }


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Implement the platform backup-plan, scoped inventory and age rules in schema/management_backup.yaml "
    "and rules/management_backup.dl using std-time and std-decision. Read decisions/platform-management-backup.md."))
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


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Derive a restore witness for exactly the tested backup in rules/management_restore.dl. "
    "Depends on test_management_backup_age_and_absence. Read decisions/platform-management-backup.md."))
def test_management_restore_matches_copy():
    from management_probes import compiled

    data = records()
    for restored_hash in ("a" * 64, "b" * 64):
        data["backup_trial"][0]["restored_hash"] = restored_hash
        model, state = compiled(data)
        expected = {("last", "restore-1")} if restored_hash == "a" * 64 else set()
        assert state.derived.get("managed_backup_restored") == expected
        if expected:
            leaves = verified("managed_backup_restored", ("last", "restore-1"), state=(model, state))
            assert ("backup_trial__backup", ("restore-1", "last")) in leaves


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Depends on the recorded disposable recovery cluster and test_management_restore_matches_copy. "
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
