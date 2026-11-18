from runpy import run_path

import pytest

from offline_cases import RUN, implementation, FIXTURE, PLAN_HASH, case


@pytest.mark.xfail(strict=True, reason="Read decisions/run-offline-acceptance.md. Implement run/offline_replay.py. Waits for the shared loop executor, price_capture, exact_quote, dispatch_policy, order_render, journal_claim, order_uncertainty, inventory_chain, cleanup_policy, installation_input and request_source.")
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
