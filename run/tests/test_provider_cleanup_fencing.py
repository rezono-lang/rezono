"""Cleanup fencing and live install-phase failure honesty in provider execution
(decisions/provider-workflow-dispatch.md)."""

from __future__ import annotations

import copy
import json
import subprocess

import pytest

from loop.replay import replay as real_loop_replay
from offline_cases import FIXTURE, PLAN_HASH, case
from run import offline_replay, provider_run


def _approved_spec(scenario: dict) -> dict:
    return {
        "plan_file": scenario["plan_file"],
        "price_file": scenario["price_file"],
        "request_file": scenario["request_file"],
        "request_sha256": scenario["request_sha256"],
        "approval": copy.deepcopy(scenario["approval"]),
        "clock": scenario["clock"],
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/provider-workflow-dispatch.md: execute_run must still invoke delete_resources and "
        "list_inventory cleanup when submit_order or order_status raises after order dispatch is attempted"
    ),
)
def test_execute_run_runs_cleanup_when_submit_order_or_order_status_raises():
    scenario = case()
    spec = _approved_spec(scenario)

    # Control: when budget refuses authorization before dispatch, neither submit_order nor cleanup runs.
    denied_spec = dict(spec, approval=dict(spec["approval"], budget_cents=161))
    denied_submit: list[str] = []
    denied_delete: list[str] = []
    denied_inventory: list[str] = []
    refused = offline_replay.execute_run(
        denied_spec,
        FIXTURE,
        claim=lambda _: True,
        submit_order=lambda key: (denied_submit.append(key), dict(scenario["order_receipt"]))[1],
        order_status=lambda _: None,
        observe_machines=lambda _: [],
        deliver=lambda _: None,
        delete_resources=lambda key: (denied_delete.append(key), dict(scenario["delete_receipt"]))[1],
        list_inventory=lambda key: (denied_inventory.append(key), copy.deepcopy(scenario["inventory"]))[1],
        scope="live",
    )
    assert refused["orders"] == 0
    assert denied_submit == []
    assert denied_delete == []
    assert denied_inventory == []

    # Case A: submit_order raises RuntimeError after being invoked.
    submit_calls_a: list[str] = []
    delete_calls_a: list[str] = []
    inventory_calls_a: list[str] = []

    def failing_submit(key: str):
        submit_calls_a.append(key)
        raise RuntimeError("submit_order failed after dispatch")

    with pytest.raises(RuntimeError, match="submit_order failed after dispatch"):
        offline_replay.execute_run(
            spec,
            FIXTURE,
            claim=lambda _: True,
            submit_order=failing_submit,
            order_status=lambda _: None,
            observe_machines=lambda _: [],
            deliver=lambda _: None,
            delete_resources=lambda key: (delete_calls_a.append(key), dict(scenario["delete_receipt"]))[1],
            list_inventory=lambda key: (inventory_calls_a.append(key), copy.deepcopy(scenario["inventory"]))[1],
            scope="live",
        )

    assert submit_calls_a == [PLAN_HASH]

    # Case B: submit_order returns None and order_status raises RuntimeError.
    submit_calls_b: list[str] = []
    status_calls_b: list[str] = []
    delete_calls_b: list[str] = []
    inventory_calls_b: list[str] = []

    def none_submit(key: str):
        submit_calls_b.append(key)
        return None

    def failing_status(key: str):
        status_calls_b.append(key)
        raise RuntimeError("order_status failed after uncertain submit")

    with pytest.raises(RuntimeError, match="order_status failed after uncertain submit"):
        offline_replay.execute_run(
            spec,
            FIXTURE,
            claim=lambda _: True,
            submit_order=none_submit,
            order_status=failing_status,
            observe_machines=lambda _: [],
            deliver=lambda _: None,
            delete_resources=lambda key: (delete_calls_b.append(key), dict(scenario["delete_receipt"]))[1],
            list_inventory=lambda key: (inventory_calls_b.append(key), copy.deepcopy(scenario["inventory"]))[1],
            scope="live",
        )

    assert submit_calls_b == [PLAN_HASH]
    assert status_calls_b == [PLAN_HASH]

    assert delete_calls_a == [PLAN_HASH], f"Case A skipped delete_resources cleanup: {delete_calls_a!r}"
    assert inventory_calls_a == [PLAN_HASH], f"Case A skipped list_inventory cleanup: {inventory_calls_a!r}"
    assert delete_calls_b == [PLAN_HASH], f"Case B skipped delete_resources cleanup: {delete_calls_b!r}"
    assert inventory_calls_b == [PLAN_HASH], f"Case B skipped list_inventory cleanup: {inventory_calls_b!r}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/provider-workflow-dispatch.md: live execute_run must not report cleanup='cleaned' or "
        "delivered=True when the install phase returns install_outcome='failed', and provider_run.main must exit non-zero"
    ),
)
def test_live_execute_run_never_reports_cleaned_when_install_phase_fails(tmp_path, monkeypatch):
    scenario = case()
    spec = _approved_spec(scenario)

    def install_failing_execute(run_id, requirements, completion, initial_rows, sweeps, limit):
        if len(requirements) == 2:
            return real_loop_replay(run_id, requirements, completion, initial_rows, sweeps, limit)
        return [["apply_installation"]], "failed"

    # 1. Direct execute_run with scope="live" and a failing install loop phase.
    result = offline_replay.execute_run(
        spec,
        FIXTURE,
        claim=lambda _: True,
        submit_order=lambda _: dict(scenario["order_receipt"]),
        order_status=lambda _: dict(scenario["order_receipt"]),
        observe_machines=lambda _: copy.deepcopy(scenario["machine_observations"]),
        deliver=lambda _: dict(scenario["installation"]),
        delete_resources=lambda _: dict(scenario["delete_receipt"]),
        list_inventory=lambda _: copy.deepcopy(scenario["inventory"]),
        scope="live",
        execute=install_failing_execute,
    )

    # 2. Full provider_run.main CLI entrypoint wired to the same failing install loop.
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8", newline="\n")
    claim_remote = tmp_path / "claims.git"
    subprocess.run(["git", "init", "--bare", "-q", str(claim_remote)], check=True)

    ports = {
        "submit_order": lambda _: dict(scenario["order_receipt"]),
        "order_status": lambda _: dict(scenario["order_receipt"]),
        "observe_machines": lambda _: copy.deepcopy(scenario["machine_observations"]),
        "deliver": lambda _: dict(scenario["installation"]),
        "delete_resources": lambda _: dict(scenario["delete_receipt"]),
        "list_inventory": lambda _: copy.deepcopy(scenario["inventory"]),
    }
    monkeypatch.setattr(offline_replay, "_loop_replay", install_failing_execute)
    monkeypatch.setattr(provider_run, "_load_ports", lambda _: ports)

    exit_code = provider_run.main(
        [
            "--spec",
            str(spec_path),
            "--fixture-dir",
            str(FIXTURE),
            "--claim-remote",
            str(claim_remote),
            "--ports",
            "run.offline_replay:unused",
            "--run-id",
            "live-install-fail-1",
        ]
    )

    assert result["cleanup"] != "cleaned", f"live execute_run reported cleanup='cleaned' despite failed install phase: {result!r}"
    assert result["delivered"] is False, f"live execute_run reported delivered=True despite failed install phase: {result!r}"
    assert exit_code != 0, f"provider_run.main exited 0 despite failed install phase: result={result!r}"
