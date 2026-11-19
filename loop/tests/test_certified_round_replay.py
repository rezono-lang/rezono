"""Replay hand-authored certificates, attempts and observations at the normal command."""
from copy import deepcopy
import json

import pytest

from loop.recording_cli import main
from test_recorded_correction import observation
from test_replay_fixed_point import boundary, execute, setup_recording


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/safe-step-rounds.md. Extend the ordinary typed recording and replay path for certified "
        "rounds. Check each recorded certificate with rezono_checker.transition and supply only admitted ones "
        "as loop_certified_step and loop_certified_member (decisions/loop-certificate-admission.md). Preserve "
        "the selected frontier, durable attempt identity, stale-cut refusal and latest observation precedence. "
        "Waits for test_supplied_verdicts_authorize_nothing, test_round_claim_is_durable_and_exclusive and "
        "test_round_submit_follows_the_certified_claim."
    ),
)
def test_certified_round_replay(tmp_path, capsys):
    data = setup_recording(tmp_path)
    data["records"]["loop_step"].append({"id": "inspect"})
    data["records"]["loop_completion"].append(
        {"id": "inspection", "step": "inspect", "run": "active", "token": "inspected", "reason": "inspection"}
    )
    data["records"]["loop_expectation"].append({"id": "inspected", "value": "yes"})
    data["initial"] = [observation("active", "permit", "seed", "permit-readback", 8, "yes")]
    data["sweeps"] = [
        boundary("lost", at=10),
        boundary("confirmed", at=11, observations=[
            observation("active", "delivery", "ship", "shipment-readback", 11, "yes"),
        ]),
        boundary("corrected", at=12, observations=[
            observation("active", "delivery", "ship", "changed-readback", 12, "no"),
        ]),
    ]
    plan_hash = "a" * 64
    data["certified_rounds"] = [
        {"run": "active", "cut": "opening", "batch": ["ship"], "certificate": "transition-a",
         "attempts": [{"step": "ship", "plan_hash": plan_hash, "state": "unknown"}]},
        {"run": "active", "cut": "lost", "batch": [], "certificate": "transition-b",
         "attempts": [{"step": "ship", "plan_hash": plan_hash, "state": "unknown"}]},
        {"run": "active", "cut": "confirmed", "batch": [], "certificate": "transition-c",
         "attempts": [{"step": "ship", "plan_hash": plan_hash, "state": "applied"}]},
        {"run": "active", "cut": "corrected", "batch": [], "certificate": "transition-d", "attempts": []},
    ]
    data["transition_certificates"] = {
        round_["certificate"]: {
            "run": round_["run"], "cut": round_["cut"], "members": list(round_["batch"]),
            "definition_sha256": data["pack"]["sha256"], "desired_manifest": "desired-publication",
        }
        for round_ in data["certified_rounds"]
    }

    status, report = execute(tmp_path, capsys, data)
    assert (status, report["outcome"], report["plans"]) == (1, "pending", [["ship"], [], []])
    assert report["submissions"] == [{"step": "ship", "plan_hash": plan_hash}]
    assert [round_["done"] for round_ in report["certified_rounds"]] == [[], [], ["ship"], []]
    assert report["certified_rounds"][1]["reserved"] == [plan_hash]

    stale = deepcopy(data)
    stale["certified_rounds"][0]["cut"] = "prior"
    recording = tmp_path / "stale-recording.json"
    recording.write_text(json.dumps(stale), encoding="utf-8")
    assert main([str(recording)]) == 1
    refused = capsys.readouterr()
    assert not refused.out and "cut" in refused.err.lower()
