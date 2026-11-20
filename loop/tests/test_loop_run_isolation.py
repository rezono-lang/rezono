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


def test_typed_recording_does_not_leak_other_run_values_with_shared_ids(tmp_path):
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
    ]
    data["records"]["loop_sweep"] = [
        {"id": "sw-1", "run": "prior", "event_time": 1, "complete": True},
    ]
    data["sweeps"] = [
        boundary(
            "sw-1",
            run="active",
            at=10,
            complete=False,
            observations=[observation("active", "sw-1", "seed", "shared", 10, "no")],
        ),
    ]

    snapshots = list(typed_recording(tmp_path, data).snapshots())
    assert snapshots[-1].drift == {("active", "seeded", "seeded", "sweep/sw-1/shared")}
    assert not snapshots[-1].fixed_point


def test_typed_recording_filters_all_run_scoped_tables_and_foreign_receipt(tmp_path, monkeypatch):
    from rezono_compiler import facts

    data = setup_recording(tmp_path)
    data["records"]["loop_requirement"].append(
        {"id": "permit-rule", "step": "ship", "run": "prior", "token": "other-token", "reason": "prior-rule"},
    )
    data["sweeps"] = [
        boundary(
            "sw-active",
            run="active",
            at=10,
            complete=False,
            observations=[observation("active", "sw-active", "seed", "permitted", 10, "yes")],
        ),
    ]
    recording = typed_recording(tmp_path, data)
    recording.records["loop_sweep_receipt"] = [{"id": "foreign-receipt", "run": "prior", "event_time": 1}]

    seen_records = []
    rows_of = facts.rows_of

    def capture_rows(model, records):
        seen_records.append(records)
        return rows_of(model, records)

    monkeypatch.setattr(facts, "rows_of", capture_rows)

    snapshots = list(recording.snapshots())
    assert any(row[:2] == ("active", "ship") for row in snapshots[-1].ready)
    assert seen_records
    assert all("loop_sweep_receipt" not in admitted for admitted in seen_records)
    assert all(
        row["run"] == "active"
        for admitted in seen_records
        for row in admitted.get("loop_requirement", ())
    )
