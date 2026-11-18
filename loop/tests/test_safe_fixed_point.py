"""An ordinary recorded round may stop only when all sources of progress are ruled out."""
from copy import deepcopy

import pytest

from test_replay_fixed_point import boundary, execute, setup_recording


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/safe-step-rounds.md. Through loop.recording_cli and the std-loop fixed-point "
        "rules, report the closed blocked goals including a goal without a producer. "
        "Waits for test_step_safety_reasons and test_batch_visible_prefixes for the integrated rule inputs."
    ),
)
def test_safe_fixed_point(tmp_path, capsys):
    recording = setup_recording(tmp_path)
    records = recording["records"]
    records["loop_goal"] = [
        {"id": "shipment", "run": "active", "token": "shipped"},
        {"id": "inventory", "run": "active", "token": "inventory-confirmed"},
    ]
    records["loop_expectation"].append({"id": "inventory-confirmed", "value": "yes"})
    records["loop_step_safety_check"] = [
        {"id": "requires-permit", "run": "active", "step": "ship", "cut": "closed",
         "obligation": "seeded", "verdict": "refuted", "reason": "failed-prerequisite"}
    ]
    recording["sweeps"] = [boundary("closed")]

    status, report = execute(tmp_path, capsys, recording)
    assert (status, report["outcome"], report["plans"]) == (1, "failure", [[]])
    assert {finding["token"] for finding in report["fixed_point"]} == {"seeded", "inventory-confirmed"}

    incomplete = deepcopy(recording)
    incomplete["sweeps"] = [boundary("closed", complete=False)]
    _, report = execute(tmp_path, capsys, incomplete)
    assert report["outcome"] == "pending" and not report.get("fixed_point")

    pending = deepcopy(recording)
    pending["records"]["loop_pending_operation"] = [
        {"id": "permit-reader", "run": "active", "token": "seeded"},
        {"id": "inventory-reader", "run": "active", "token": "inventory-confirmed"},
    ]
    _, report = execute(tmp_path, capsys, pending)
    assert report["outcome"] == "pending" and not report.get("fixed_point")

    deferred = deepcopy(recording)
    deferred["records"]["loop_goal"] = records["loop_goal"][:1]
    deferred["records"]["loop_step_safety_check"][0].update(verdict="proved", reason="variant-valid")
    deferred["records"]["loop_batch_deferral"] = [
        {"id": "ship-deferred", "run": "active", "step": "ship", "cut": "closed", "batch": "selected-batch"}
    ]
    _, report = execute(tmp_path, capsys, deferred)
    assert report["outcome"] == "pending" and not report.get("fixed_point")
