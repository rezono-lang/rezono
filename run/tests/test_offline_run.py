from runpy import run_path

import pytest

from offline_cases import RUN, implementation, FIXTURE, PLAN_HASH, case


def test_offline_run(tmp_path):
    replay = implementation("offline_replay.py", "replay")
    execute = run_path(str(RUN.parent / "loop" / "replay.py"))["replay"]
    phases = []

    def observed_execute(*args, **kwargs):
        phases.append(execute(*args, **kwargs))
        return phases[-1]

    scenario = case()
    result = replay(scenario, FIXTURE, tmp_path / "complete.sqlite", execute=observed_execute)
    assert len(phases) == 2
    assert result == {"plan_hash": PLAN_HASH, "cost_micros": 1614000, "orders": 1,
                      "request": "sample", "delivered": True, "cleanup": "cleaned",
                      "sweep": "after", "loop_phases": ["order", "installation"],
                      "operations": scenario["operations"]}
    restarted = replay(scenario, FIXTURE, tmp_path / "complete.sqlite", execute=execute)
    assert restarted["orders"] == 0 and restarted["cleanup"] == "cleaned"
    incomplete = dict(scenario, inventory=scenario["inventory"][:-1])
    pending = replay(incomplete, FIXTURE, tmp_path / "pending.sqlite", execute=execute)
    assert pending["cleanup"] == "unknown" and pending["orders"] == 1
    denied = dict(scenario, approval=dict(scenario["approval"], budget_cents=161))
    refused = replay(denied, FIXTURE, tmp_path / "refused.sqlite", execute=execute)
    assert refused["orders"] == 0 and refused["delivered"] is False
    wrong = dict(scenario, installation={"request_id": "another", "ready": True})
    assert replay(wrong, FIXTURE, tmp_path / "wrong.sqlite", execute=execute)["delivered"] is False


def test_offline_run_validation_and_cleanup_consistency(tmp_path):
    from hashlib import sha256
    import json
    import shutil

    from rezono_compiler import pack

    replay = implementation("offline_replay.py", "replay")
    dispatch_authorized = implementation("offline_replay.py", "_dispatch_authorized")
    execute = run_path(str(RUN.parent / "loop" / "replay.py"))["replay"]
    scenario = case()

    # Wrong delivery never runs delete_resources or list_inventory, so cleanup stays unknown.
    wrong = dict(scenario, installation={"request_id": "another", "ready": True})
    wrong_result = replay(wrong, FIXTURE, tmp_path / "wrong-cleanup.sqlite", execute=execute)
    assert wrong_result["delivered"] is False
    assert "delete_resources" not in wrong_result["operations"]
    assert "list_inventory" not in wrong_result["operations"]
    assert wrong_result["cleanup"] == "unknown"

    # A plan missing request_id must not be reported as delivered.
    no_req_dir = tmp_path / "missing-request-id"
    shutil.copytree(FIXTURE, no_req_dir)
    plan_data = json.loads((no_req_dir / "plan.json").read_text(encoding="utf-8"))
    del plan_data["request_id"]
    plan_bytes = json.dumps(plan_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (no_req_dir / "plan.json").write_bytes(plan_bytes)
    new_hash = sha256(plan_bytes).hexdigest()
    no_req_scenario = dict(
        scenario,
        approval=dict(scenario["approval"], plan_hash=new_hash),
        order_receipt=dict(scenario["order_receipt"], plan_hash=new_hash),
        inventory=[
            dict(
                page,
                resources=[
                    dict(res, plan_hash=new_hash) if res.get("plan_hash") == PLAN_HASH else res
                    for res in page["resources"]
                ],
            )
            for page in scenario["inventory"]
        ],
    )
    no_req_result = replay(no_req_scenario, no_req_dir, tmp_path / "no-req.sqlite", execute=execute)
    assert no_req_result["delivered"] is False
    assert no_req_result["cleanup"] == "unknown"

    # Out-of-range cost_micros must raise ValueError cleanly before DuckDB ingestion.
    for bad_cost in (-1, pack.BIGINT[1] + 1):
        with pytest.raises(ValueError):
            dispatch_authorized(PLAN_HASH, "USD", bad_cost, scenario["approval"], 0)

    overflow_dir = tmp_path / "overflow-cost"
    shutil.copytree(FIXTURE, overflow_dir)
    overflow_plan = json.loads((overflow_dir / "plan.json").read_text(encoding="utf-8"))
    overflow_plan["lines"] = [{"billed_periods": 1, "quantity": 10**14, "sku": "vbm-4c-32gb"}]
    overflow_bytes = json.dumps(overflow_plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (overflow_dir / "plan.json").write_bytes(overflow_bytes)
    overflow_hash = sha256(overflow_bytes).hexdigest()
    overflow_scenario = dict(scenario, approval=dict(scenario["approval"], plan_hash=overflow_hash))
    with pytest.raises(ValueError):
        replay(overflow_scenario, overflow_dir, tmp_path / "overflow.sqlite", execute=execute)
