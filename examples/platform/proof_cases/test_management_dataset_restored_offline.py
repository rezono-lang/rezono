"""Read a named restored dataset while a single management fence covers the live trial."""

from datetime import datetime
import re

import pytest

from management_probes import live_events


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Depends on test_management_backup_restore_readback, recorded dataset-to-copy binding and management "
    "fence coverage in the same disposable trial. Read decisions/safe-step-rounds.md, section 4. "
    "Read named dataset bytes in isolated recovery through shared backup recorder evidence."))
def test_management_dataset_restored_offline():
    events = live_events("backup")

    def one(kind):
        matches = [event for event in events if event["kind"] == kind]
        assert len(matches) == 1, (kind, len(matches))
        return matches[0]

    binding = one("management-dataset-bound")
    captured = one("backup-completed")
    readback = one("recovered-read")
    hold = one("management-fence-acquired")
    coverage = one("management-fence-coverage")
    probes = [event for event in events if event["kind"] == "management-unreachable"]
    assert len(probes) >= 2
    opening, closing = probes[0], probes[-1]

    trial = binding["trial"]
    assert trial and all(event["trial"] == trial for event in (readback, hold, coverage, *probes))
    assert binding["dataset"] == readback["dataset"] == "management-catalog"
    assert binding["backup"] == captured["backup"] == readback["backup"]
    assert binding["source_evidence"] == captured["evidence"] == readback["source_evidence"]
    assert captured["source_cluster"] == "management" and readback["cluster"] == "recovery"
    assert readback["isolated"] is True and readback["active_authority"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", readback["payload_sha256"])
    assert binding["payload_sha256"] == captured["payload_sha256"] == readback["payload_sha256"]
    assert len({trial, captured["evidence"], readback["evidence"]}) == 3

    assert all(event["cluster"] == "management" and event["probe_result"] == "unreachable" for event in probes)
    assert hold["cluster"] == coverage["cluster"] == "management"
    assert hold["fence"] and hold["fence"] == coverage["fence"]
    assert coverage["fence_evidence"] == hold["evidence"]
    assert coverage["complete"] is True and coverage["lost"] == 0
    assert coverage["opening_probe"] == opening["evidence"] and coverage["closing_probe"] == closing["evidence"]
    assert coverage["readback_evidence"] == readback["evidence"]
    assert all(event["kind"] not in {"management-reachable", "management-fence-broken", "management-authority-enabled"}
               for event in events[events.index(hold):events.index(closing) + 1])

    def at(event):
        return datetime.fromisoformat(event["observed_at"])

    assert at(captured) <= at(binding) < at(hold) <= at(opening) < at(readback) < at(closing) <= at(coverage)
    assert at(hold) <= datetime.fromisoformat(coverage["start"]) <= at(opening)
    assert at(closing) <= datetime.fromisoformat(coverage["end"]) <= at(coverage)
    assert len({event["evidence"] for event in (binding, captured, readback, hold, coverage, *probes)}) == len(probes) + 5
