"""Replay independent sweep receipts and observation envelopes through the ordinary command."""
import json
import shutil

import pytest
import yaml

from pack_records import LOOP, evaluate
from rezono_compiler import modules, pack
from test_recorded_correction import observation
from loop.recording_cli import main


def setup_recording(tmp_path):
    for pack in (LOOP, LOOP.parent / "std-order"):
        shutil.copytree(pack, tmp_path / pack.name)
    reader_file = LOOP.parents[1] / "contracts/fixtures/port/Port/valid/in.yaml"
    reader = yaml.safe_load(reader_file.read_bytes())
    reader.update(name="recorded-status", produces=["loop_observation"], secrets=[])
    return {
        "run": "active", "limit": 6, "initial": [], "sweeps": [], "ports": [reader],
        "pack": {"path": "std-loop", "sha256": modules.pack_hash(tmp_path / "std-loop")},
        "records": {
            "loop_active_run": [{"id": "active"}],
            "loop_step": [{"id": "ship"}],
            "loop_completion": [{"id": "ship-definition", "step": "ship", "run": "active",
                                 "token": "shipped", "reason": "ship-definition"}],
            "loop_requirement": [{"id": "permit-rule", "step": "ship", "run": "active",
                                  "token": "seeded", "reason": "permit-rule"}],
            "loop_expectation": [{"id": t, "value": "yes"} for t in ("seeded", "shipped")],
        },
    }


def boundary(key, *, complete=True, run="active", observations=(), at=10):
    return {"id": key, "run": run, "event_time": at, "complete": complete,
            "observations": list(observations)}


def execute(tmp_path, capsys, recording):
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    status = main([str(path)])
    output = capsys.readouterr()
    assert output.out, output.err
    return status, json.loads(output.out)


def test_wait_for_observed_permission(tmp_path, capsys):
    data = setup_recording(tmp_path)
    permit = observation("active", "permission", "seed", "signed-permit", 10, "yes")
    confirmed = observation("active", "delivery", "ship", "shipment-readback", 11, "yes")
    data["sweeps"] = [[permit], [confirmed]]
    status, report = execute(tmp_path, capsys, data)
    assert (status, report["outcome"], report["plans"]) == (0, "success", [[], ["ship"]])


@pytest.mark.parametrize("first_kind", ["partial", "foreign", "pending", "ready-producer"])
def test_possible_progress_survives_quiet_sweep(tmp_path, capsys, first_kind):
    data = setup_recording(tmp_path)
    first = boundary("quiet", complete=first_kind != "partial",
                     run="prior" if first_kind == "foreign" else "active")
    if first_kind == "pending":
        data["records"]["loop_pending_operation"] = [{"id": "approval-request", "run": "active", "token": "seeded"}]
    if first_kind == "ready-producer":
        data["records"]["loop_step"].append({"id": "supply"})
        data["records"]["loop_completion"].append(
            {"id": "supply-def", "run": "active", "step": "supply", "token": "seeded", "reason": "supply-def"})
    permit = observation("active", "permission", "seed", "signed-permit", 10, "yes")
    confirmed = observation("active", "delivery", "ship", "shipment-readback", 11, "yes")
    data["sweeps"] = [first, [permit], [confirmed]]
    status, report = execute(tmp_path, capsys, data)
    assert (status, report["outcome"], report["rounds"]) == (0, "success", 3)
    assert report["plans"][-1] == ["ship"]


@pytest.mark.parametrize("last", [[], [boundary("partial", complete=False)], [boundary("foreign", run="prior")]])
def test_uncovered_waiting_steps_remain_pending(tmp_path, capsys, last):
    data = setup_recording(tmp_path)
    data["sweeps"] = last
    status, report = execute(tmp_path, capsys, data)
    assert (status, report) == (1, {"outcome": "pending", "plans": [[]] * len(last), "rounds": len(last)})


@pytest.mark.parametrize("complete", [True, False], ids=["complete", "partial"])
def test_pending_completion_survives_quiet_sweep(tmp_path, capsys, complete):
    data = setup_recording(tmp_path)
    data["records"]["loop_pending_operation"] = [
        {"id": "shipment-in-flight", "run": "active", "token": "shipped"},
    ]
    data["sweeps"] = [boundary("quiet", complete=complete)]
    assert execute(tmp_path, capsys, data) == (1, {"outcome": "pending", "plans": [[]], "rounds": 1})

    confirmed = observation("active", "delivery", "ship", "shipment-readback", 11, "yes")
    data["sweeps"].append([confirmed])
    assert execute(tmp_path, capsys, data) == (0, {"outcome": "success", "plans": [[], []], "rounds": 2})


def test_complete_quiet_sweep_publishes_fixed_point_witness(tmp_path, capsys):
    data = setup_recording(tmp_path)
    records = data["records"]
    records["loop_pending_operation"] = [
        {"id": "foreign-request", "run": "prior", "token": "seeded"},
        {"id": "foreign-shipment", "run": "prior", "token": "shipped"},
        {"id": "unrelated-request", "run": "active", "token": "unrelated"},
        {"id": "previous-inspection", "run": "active", "token": "inspected"},
    ]
    records["loop_step"].append({"id": "inspect"})
    records["loop_completion"] += [
        {"id": "inspection-definition", "run": "active", "step": "inspect",
         "token": "inspected", "reason": "inspection-definition"},
        {"id": "foreign-definition", "run": "prior", "step": "ship",
         "token": "unrelated", "reason": "foreign-definition"},
    ]
    records["loop_expectation"].append({"id": "inspected", "value": "yes"})
    records["loop_observation"] = [
        {"id": "inspection-readback", "run": "active", "token": "inspected", "event_time": 9,
         "state": "known", "value": "yes", "reason": "inspection-readback"},
    ]
    permit = observation("active", "late", "seed", "signed-permit", 11, "yes")
    data["sweeps"] = [boundary("closed-inventory"), [permit]]
    status, report = execute(tmp_path, capsys, data)
    assert (status, report["outcome"], report["plans"]) == (1, "failure", [[]])
    assert report["fixed_point"] == [{"run": "active", "sweep": "closed-inventory", "step": "ship",
                                      "token": "seeded", "requirement": "permit-rule"}]

    # Verify the compiled explanation cites the source records, independently of their reason strings.
    records["loop_requirement"][0]["id"] = "prerequisite-source-row"
    records["loop_sweep_receipt"] = [{"id": "closed-inventory", "run": "active", "event_time": 10}]
    program, rows, explainer = evaluate(pack.read(LOOP), records)
    row, = rows["fixed_point"]
    proof = explainer.proof("fixed_point", row, "fixture")
    source_ids = {json.loads(p["row"]["key"])[0] for witness in proof["witnesses"]
                  for p in witness["premises"] if p["polarity"] == "positive"
                  and p["row"]["relation"] in program.base_used()}
    assert {"closed-inventory", "prerequisite-source-row"} <= source_ids
