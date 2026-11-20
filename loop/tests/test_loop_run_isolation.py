"""Verify executor sweep run checking and run-scoped record deduplication in typed recordings."""

import pytest

from loop.executor import execute
from loop.typed_recording import typed_recording
from test_apply_readback_executor import bootstrap
from test_recorded_correction import observation
from test_replay_fixed_point import boundary, setup_recording


def test_admit_sweep_rejects_foreign_run(tmp_path):
    data = bootstrap(tmp_path)

    with pytest.raises(ValueError, match="run"):
        execute(
            tmp_path,
            data,
            apply=lambda run, round_number, step: "applied",
            read=lambda run, round_number: boundary(f"round-{round_number}", run="other", at=10 + round_number),
        )


def test_typed_recording_scopes_record_ids_by_run(tmp_path):
    data = setup_recording(tmp_path)
    data["records"]["loop_observation"] = [
        {
            "id": "recorded-status/shared",
            "run": "prior",
            "token": "seeded",
            "event_time": 1,
            "state": "known",
            "value": "yes",
            "reason": "prior-seed",
        },
        {
            "id": "recorded-status/shared",
            "run": "other",
            "token": "seeded",
            "event_time": 2,
            "state": "known",
            "value": "yes",
            "reason": "other-seed",
        },
    ]
    data["records"]["loop_sweep"] = [
        {"id": "shared-sweep", "run": "prior", "event_time": 1, "complete": True},
        {"id": "shared-sweep", "run": "other", "event_time": 2, "complete": True},
    ]
    data["sweeps"] = [
        boundary(
            "shared-sweep",
            run="active",
            at=10,
            complete=True,
            observations=[observation("active", "shared-sweep", "seed", "shared", 10, "yes")],
        ),
    ]

    snapshots = list(typed_recording(tmp_path, data).snapshots())
    assert any(row[:2] == ("active", "ship") for row in snapshots[-1].ready)

    data["records"]["loop_sweep"].append(
        {"id": "shared-sweep", "run": "prior", "event_time": 3, "complete": False},
    )
    with pytest.raises(ValueError, match="conflicting records for sweep"):
        list(typed_recording(tmp_path, data).snapshots())
