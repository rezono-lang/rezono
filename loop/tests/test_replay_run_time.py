"""A replay compares stored ticks and source instants on one run's clock."""

import json
import shutil

import pytest
import yaml

from test_recorded_correction import observation
from wire_fixtures import ROOT, entry


@pytest.fixture
def recording(tmp_path):
    from rezono_compiler.modules import pack_hash

    repo = ROOT.parent
    for name in ("std-order", "std-loop"):
        shutil.copytree(repo / "packs" / name, tmp_path / name)
    port = repo / "contracts" / "fixtures" / "port" / "Port" / "valid" / "in.yaml"
    reader = yaml.safe_load(port.read_text(encoding="utf-8"))
    reader.update(name="recorded-status", consumes=["loop_step"], produces=["loop_observation"], secrets=[])
    return {
        "run": "active",
        "limit": 2,
        "ports": [reader],
        "pack": {"path": "std-loop", "sha256": pack_hash(tmp_path / "std-loop")},
        "records": {
            "loop_active_run": [{"id": "active"}],
            "loop_step": [{"id": "seed"}],
            "loop_completion": [
                {"id": "done-seeding", "run": "active", "step": "seed", "token": "seeded", "reason": "plan"},
            ],
            "loop_expectation": [{"id": "seeded", "value": "yes"}],
            "loop_observation": [
                {"id": "stored", "run": "active", "token": "seeded", "event_time": 5,
                 "state": "known", "value": "no", "reason": "stored-refusal"},
            ],
        },
        "initial": [
            observation("active", "first", "seed", "clock-start", 10, "no"),
            observation("active", "first", "seed", "confirmed", 12, "yes"),
        ],
        "sweeps": [],
    }


def replay(recording, tmp_path, monkeypatch, capsys):
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    main = entry(monkeypatch, "recording_cli", "main")
    status = main([str(path)])
    return status, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("foreign_time", ["00:00:01Z", "00:00:59.001Z"], ids=["earlier-origin", "finer-precision"])
def test_foreign_observation_does_not_change_the_active_clock(
    recording, tmp_path, monkeypatch, capsys, foreign_time
):
    expected = (1, {"plans": [], "outcome": "failure", "rounds": 0})
    assert replay(recording, tmp_path, monkeypatch, capsys) == expected

    foreign = observation("other", "first", "seed", "foreign", 59, "yes")
    foreign["observation"]["event_time"] = f"2026-01-01T{foreign_time}"
    recording["initial"].append(foreign)

    assert replay(recording, tmp_path, monkeypatch, capsys) == expected


def test_later_active_observation_can_supersede_stored_evidence(recording, tmp_path, monkeypatch, capsys):
    recording["initial"][1]["observation"]["event_time"] = "2026-01-01T00:00:16Z"
    assert replay(recording, tmp_path, monkeypatch, capsys) == (
        0, {"plans": [], "outcome": "success", "rounds": 0}
    )
