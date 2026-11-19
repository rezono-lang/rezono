"""A restore trial that does not depend on an unavailable cluster and lacks a binding is unknown."""

import pytest

from management_probes import compiled


RUN, TRIAL, BACKUP, RECOVERY = "restore-run", "restore-trial", "chosen-copy", "recovery"
MISSING = (RUN, TRIAL, BACKUP, "unknown", "missing-dependency-binding", RECOVERY)


def control_on(cluster):
    """Only the control plane is bound, and it was read as available where it is bound."""
    return {
        "restore_dependency_binding": [{"id": "control", "trial": TRIAL, "function": "control",
                                        "provider": "recovery-api", "cluster": cluster}],
        "restore_dependency_reading": [{"id": "observed-control", "run": RUN, "trial": TRIAL,
                                        "provider": "recovery-api", "cluster": cluster, "value": "available"}],
    }


# Expectations written from decisions/safe-step-rounds.md, section 4: control plane, credentials and storage
# must all be bound; a control plane outside the trial's own recovery cluster is a separate reason.
CASES = {
    "without bindings": ({}, {MISSING}),
    "only control on recovery": (control_on(RECOVERY), {MISSING}),
    "only control on available management": (control_on("management"), {
        MISSING, (RUN, TRIAL, BACKUP, "unknown", "foreign-control-plane", "recovery-api")}),
}


@pytest.mark.parametrize("case", CASES)
def test_restore_offline_missing_binding_is_unknown(case):
    extra, expected = CASES[case]
    records = {"backup_trial": [{"id": TRIAL, "backup": BACKUP, "cluster": RECOVERY, "run": RUN}], **extra}
    _, state = compiled(records)
    assert not state.derived.get("unavailable_service")
    assert state.derived["restore_offline_result"] == expected
