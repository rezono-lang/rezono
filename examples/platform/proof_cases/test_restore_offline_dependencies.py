"""A matching restore copy and independent operational prerequisites are separate grounds."""

from copy import deepcopy
from hashlib import sha256

import pytest

from case_support import verified
from management_probes import compiled


def test_restore_offline_dependencies():
    run, trial, backup, recovery = "restore-run", "restore-trial", "chosen-copy", "recovery"
    digest = sha256(b"authored recovery payload\n").hexdigest()
    exact_copy = {
        "backup_trial": [{"id": trial, "backup": backup, "cluster": recovery, "run": run}],
        "backup_capture": [{"id": "capture", "backup": backup, "source_cluster": "management", "run": run,
                            "payload_sha256": digest}],
        "backup_readback": [{"id": "readback", "backup": backup, "cluster": recovery, "run": run,
                             "trial": trial, "source_evidence": "capture", "payload_sha256": digest}],
    }
    _, state = compiled(exact_copy)
    assert state.derived.get("managed_backup_restored") == {(backup, trial)}
    relation = "restore_offline_result"
    assert relation in state.derived, "Missing platform offline restore dependency results"

    bindings = (("control", "recovery-api", recovery), ("credentials", "recovery-key", recovery),
                ("storage", "backup-store", "storage"))
    records = exact_copy | {
        "restore_dependency_binding": [
            {"id": function, "trial": trial, "function": function, "provider": provider, "cluster": cluster}
            for function, provider, cluster in bindings
        ],
        "restore_dependency_reading": [
            {"id": f"observed-{function}", "run": run, "trial": trial, "provider": provider, "cluster": cluster,
             "value": "available"}
            for function, provider, cluster in bindings
        ],
        "failure_observation": [{"id": "management"}],
    }
    restored = (run, trial, backup, "restored", "matching-copy", recovery)
    model, state = compiled(records)
    assert state.derived[relation] == {restored}
    assert {
        ("restore_dependency_binding__cluster", ("control", recovery)),
        ("restore_dependency_reading__value", ("observed-control", "available")),
        ("restore_dependency_reading__value", ("observed-credentials", "available")),
        ("restore_dependency_reading__value", ("observed-storage", "available")),
        ("backup_capture__payload_sha256", ("capture", digest)),
        ("backup_readback__source_evidence", ("readback", "capture")),
        ("backup_readback__payload_sha256", ("readback", digest)),
    } <= verified(relation, restored, state=(model, state))

    dependent = deepcopy(records)
    dependent["restore_dependency_binding"][0]["cluster"] = "management"
    model, state = compiled(dependent)
    waiting = (run, trial, backup, "waiting", "management-dependent", "recovery-api")
    assert state.derived[relation] == {waiting}
    assert {
        ("restore_dependency_binding__cluster", ("control", "management")),
        ("failure_observation", ("management",)),
    } <= verified(relation, waiting, state=(model, state))

    missing = deepcopy(records)
    missing["restore_dependency_reading"][1]["run"] = "previous-run"
    _, state = compiled(missing)
    assert state.derived[relation] == {(run, trial, backup, "unknown", "missing-dependency-readback", "recovery-key")}

    wrong_bytes = sha256(b"different recovery payload\n").hexdigest()
    for wrong_readback in ({"payload_sha256": wrong_bytes}, {"trial": "other-trial"}):
        bad = deepcopy(records)
        bad["backup_readback"][0].update(wrong_readback)
        _, state = compiled(bad)
        assert state.derived["managed_backup_restored"] == set()
        assert state.derived[relation] == {(run, trial, backup, "waiting", "missing-matching-readback", recovery)}


def test_restore_offline_requires_every_readback_on_target():
    """Restored needs every binding read, no contradicting reading and the trial's own control plane."""
    run, trial, backup, recovery = "restore-run", "restore-trial", "chosen-copy", "recovery"
    digest = sha256(b"authored recovery payload\n").hexdigest()
    bindings = (("control", "recovery-api", recovery), ("credentials", "recovery-key", recovery),
                ("storage", "backup-store", "storage"))
    records = {
        "backup_trial": [{"id": trial, "backup": backup, "cluster": recovery, "run": run}],
        "backup_capture": [{"id": "capture", "backup": backup, "source_cluster": "management", "run": run,
                            "payload_sha256": digest}],
        "backup_readback": [{"id": "readback", "backup": backup, "cluster": recovery, "run": run,
                             "trial": trial, "source_evidence": "capture", "payload_sha256": digest}],
        "restore_dependency_binding": [
            {"id": function, "trial": trial, "function": function, "provider": provider, "cluster": cluster}
            for function, provider, cluster in bindings
        ],
        "restore_dependency_reading": [
            {"id": f"observed-{function}", "run": run, "trial": trial, "provider": provider, "cluster": cluster,
             "value": "available"}
            for function, provider, cluster in bindings
        ],
        "failure_observation": [{"id": "management"}],
    }
    relation = "restore_offline_result"

    def results(change):
        changed = deepcopy(records)
        change(changed)
        return compiled(changed)[1].derived[relation]

    assert results(lambda r: None) == {(run, trial, backup, "restored", "matching-copy", recovery)}

    def unread(function, provider, cluster):
        return lambda r: r["restore_dependency_binding"].append(
            {"id": f"extra-{function}", "trial": trial, "function": function, "provider": provider, "cluster": cluster})

    assert results(unread("dns", "dns-svc", recovery)) == {
        (run, trial, backup, "unknown", "missing-dependency-readback", "dns-svc")}
    assert results(unread("storage", "other-store", "storage")) == {
        (run, trial, backup, "unknown", "missing-dependency-readback", "other-store")}

    def contradicted(r):
        r["restore_dependency_reading"].append({"id": "observed-control-later", "run": run, "trial": trial,
                                                "provider": "recovery-api", "cluster": recovery,
                                                "value": "unavailable"})

    assert results(contradicted) == {(run, trial, backup, "unknown", "conflicting-dependency-readback", "recovery-api")}

    def elsewhere(r):
        r["restore_dependency_binding"][0]["cluster"] = "elsewhere"
        r["restore_dependency_reading"][0]["cluster"] = "elsewhere"

    assert results(elsewhere) == {(run, trial, backup, "unknown", "foreign-control-plane", "recovery-api")}


def test_restore_offline_dependent_trial_without_every_binding_only_waits():
    """A trial whose only binding is a control plane on an unavailable cluster waits; it is not also unknown."""
    run, trial, backup, recovery = "restore-run", "restore-trial", "chosen-copy", "recovery"
    records = {
        "backup_trial": [{"id": trial, "backup": backup, "cluster": recovery, "run": run}],
        "restore_dependency_binding": [{"id": "control", "trial": trial, "function": "control",
                                        "provider": "recovery-api", "cluster": "management"}],
        "failure_observation": [{"id": "management"}],
    }
    _, state = compiled(records)
    assert state.derived["restore_offline_result"] == {
        (run, trial, backup, "waiting", "management-dependent", "recovery-api")}
