"""Offline replay of the partial Flatcar KubeVirt host observation."""
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "flatcar-kubevirt-host.json"


def read_record():
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def check_partial_trial(record):
    rows = record["observations"]
    assert [row["event"] for row in rows] == [
        "node_condition", "lease_renewal", "node_identity", "operator_rollout",
        "kvm_allocation", "vmi", "launcher", "failure",
    ]
    times = [datetime.fromisoformat(row["time"]) for row in rows]
    assert all(time.tzinfo == timezone.utc for time in times)
    assert all(before < after for before, after in zip(times, times[1:]))

    condition, lease, node, operator, allocation, vmi, launcher, failure = rows
    assert (condition["type"], condition["status"], condition["reason"]) == ("Ready", "True", "KubeletReady")
    assert "Flatcar" in node["os"] and node["os"].endswith("4757.2.3")
    assert node["kubelet"] == "v1.36.6+k0s"
    first, second = lease["samples"]
    assert first["uid"] == second["uid"]
    start, end = (datetime.fromisoformat(row["renew_time"]) for row in (first, second))
    assert start.tzinfo == end.tzinfo == timezone.utc and start < end <= times[1]

    assert (operator["name"], operator["result"]) == ("virt-operator", "success")
    assert allocation["available"] is True
    assert (allocation["raw_capacity"], allocation["capacity"]) == ("1k", 1000)
    assert allocation["node"] == vmi["node"] == launcher["node"] == node["name"] == "proof-worker"
    assert (vmi["name"], vmi["phase"]) == ("host-probe", "Running") and vmi["ready"] is True
    assert launcher["controller_vmi_uid"] == vmi["uid"]
    assert len({UUID(row["uid"]) for row in (node, first, vmi, launcher)}) == 4

    assert (record["conclusion"], failure["stage"], failure["exit_code"]) == ("failure", "guest-console", 1)
    assert record["guest_console"] == "unconfirmed" and record["live_kvm_vcpu"] == "not_run"


def test_recorded_flatcar_host_stops_at_console():
    record = read_record()
    assert record["job"] == (
        "https://github.com/rezono-lang/rezono/actions/runs/44252183769/job/134625269003"
    )
    assert record["revision"] == "7496834442da3995b19fde11eb9abe9c488bbba3"
    check_partial_trial(record)


@pytest.mark.parametrize(("event", "field", "value"), [
    ("vmi", "node", "other-worker"),
    ("launcher", "controller_vmi_uid", "00000000-0000-4000-8000-000000000001"),
    ("failure", "stage", "live-kvm-vcpu"),
])
def test_mismatched_observations_are_rejected(event, field, value):
    record = read_record()
    next(row for row in record["observations"] if row["event"] == event)[field] = value
    with pytest.raises(AssertionError):
        check_partial_trial(record)


@pytest.mark.parametrize("field", ["uid", "renew_time"])
def test_stale_or_replaced_lease_is_rejected(field):
    record = read_record()
    first, second = next(row["samples"] for row in record["observations"] if row["event"] == "lease_renewal")
    second[field] = "00000000-0000-4000-8000-000000000002" if field == "uid" else first["renew_time"]
    with pytest.raises(AssertionError):
        check_partial_trial(record)


@pytest.mark.parametrize("field", ["guest_console", "live_kvm_vcpu"])
def test_unobserved_guest_evidence_is_rejected(field):
    record = read_record()
    record[field] = "confirmed"
    with pytest.raises(AssertionError):
        check_partial_trial(record)
