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
