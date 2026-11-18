"""Replay the sanitized controller observations without network or a hypervisor."""

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID

SOURCE = Path(__file__).resolve().parents[1] / "fixtures" / "registered-flatcar-worker.json"


def test_recorded_worker_reaches_ready_with_a_lease():
    events = json.loads(SOURCE.read_text(encoding="utf-8"))["observations"]
    assert [row["event"] for row in events] == [
        "controller_ready", "ignition_rendered", "first_boot", "worker_installed",
        "node_registered", "node_condition", "node_identity",
    ]
    times = [datetime.fromisoformat(row["time"]) for row in events]
    assert all(t.tzinfo == timezone.utc for t in times)
    assert all(earlier < later for earlier, later in zip(times, times[1:]))
    assert events[0]["nodes"] == 0
    registration, condition, identity = events[-3:]
    assert registration["name"] == identity["name"] == "proof-worker"
    assert UUID(identity["uid"]).int != 0
    assert identity["os"].endswith("4757.2.3") and "Flatcar" in identity["os"]
    assert identity["kubelet"] == "v1.36.6+k0s"
    assert (condition["type"], condition["status"], condition["reason"]) == (
        "Ready", "True", "KubeletReady",
    )
    assert identity["ready"] is True
    assert identity["lease_renew_time_present"] is True
