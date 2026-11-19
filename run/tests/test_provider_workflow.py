"""Check the operator workflow's dispatch structure without running any job."""
from graphlib import TopologicalSorter
from pathlib import Path

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/provider-run.yml"
VERIFY_REF = 'test "$GITHUB_REF" = refs/heads/main'
AFTER_FAILURE = "failure() && needs.verify_ref.result == 'success'"
AFTER_ANY = "always() && needs.verify_ref.result == 'success'"


def condition(node):
    value = node.get("if", "success()").strip()
    if value.startswith("${{") and value.endswith("}}"):
        return value[3:-2].strip()
    return value


def check_boundary(doc):
    triggers = doc["on"]
    if isinstance(triggers, dict):
        assert set(triggers) == {"workflow_dispatch"}
        options = triggers["workflow_dispatch"]
        assert options in ("", None) or (isinstance(options, dict) and options.keys() <= {"inputs"})
    else:
        assert triggers in ("workflow_dispatch", ["workflow_dispatch"])

    jobs = doc["jobs"]
    gate = jobs["verify_ref"]
    # needs.verify_ref.result must describe this exact check, including failure.
    assert gate.keys() <= {"name", "runs-on", "steps", "environment", "timeout-minutes"}
    assert gate.get("runs-on")
    gate_env = gate.get("environment", "provider-run")
    assert (gate_env.get("name") if isinstance(gate_env, dict) else gate_env) == "provider-run"
    step, = gate["steps"]
    assert step.keys() <= {"name", "id", "shell", "run"}
    assert step["shell"] in {"sh", "bash"} and step["run"].strip() == VERIFY_REF

    dependencies = {}
    for name, job in jobs.items():
        needs = job.get("needs", [])
        dependencies[name] = [needs] if isinstance(needs, str) else needs
        assert set(dependencies[name]) <= jobs.keys()

    # Ordinary successful dependencies propagate ref verification transitively.
    # A status-function override must check the direct result even for cleanup.
    on_success = {"verify_ref": True}
    for name in TopologicalSorter(dependencies).static_order():
        if name == "verify_ref":
            continue
        job = jobs[name]
        env = job.get("environment")
        assert (env.get("name") if isinstance(env, dict) else env) == "provider-run"
        assert job.get("runs-on") and job.get("steps") and "uses" not in job
        needs = dependencies[name]
        assert needs, "an executable job can start without ref verification"
        when = condition(job)
        if when == "success()":
            on_success[name] = all(on_success[dep] for dep in needs)
        else:
            assert when in {AFTER_ANY, AFTER_FAILURE} and "verify_ref" in needs
            on_success[name] = when == AFTER_ANY

    assert on_success.get("provider_run"), "no provider job is reachable on a normal main dispatch"
    assert any(condition(step) == "success()" and (step.get("run") or step.get("uses"))
               for step in jobs["provider_run"]["steps"])


def example():
    # These local case bodies deliberately model no order or provider access.
    return {"on": {"workflow_dispatch": {}}, "jobs": {
        "verify_ref": {"runs-on": "ubuntu-24.04", "steps": [{"shell": "bash", "run": VERIFY_REF}]},
        "prepare": {"runs-on": "ubuntu-24.04", "environment": "provider-run",
                    "needs": "verify_ref", "steps": [{"run": "echo prepare"}]},
        "provider_run": {"runs-on": "ubuntu-24.04", "environment": {"name": "provider-run"},
                         "needs": "prepare", "steps": [{"run": "echo fixture"}, {"if": "failure()", "run": "echo cleanup"}]},
        "cleanup": {"runs-on": "ubuntu-24.04", "environment": "provider-run", "needs": ["verify_ref", "provider_run"],
                    "if": AFTER_FAILURE, "steps": [{"run": "echo cleanup"}]},
    }}


@pytest.mark.parametrize("events", ["workflow_dispatch", ["workflow_dispatch"], {"workflow_dispatch": {}}])
@pytest.mark.parametrize("shell", ["sh", "bash"])
def test_main_dispatch_with_preparation_and_cleanup(events, shell):
    doc = example()
    doc["on"] = events
    doc["jobs"]["verify_ref"]["steps"][0]["shell"] = shell
    check_boundary(doc)


@pytest.mark.parametrize("other", ["push", "pull_request", "workflow_call", "schedule"])
def test_extra_trigger_is_rejected(other):
    doc = example()
    doc["on"][other] = {}
    with pytest.raises(AssertionError):
        check_boundary(doc)


@pytest.mark.parametrize(("job", "key", "wrong"), [
    ("verify_ref", "continue-on-error", True),
    ("verify_ref", "steps", [{"shell": "sh", "run": 'test "$GITHUB_REF_NAME" = main'}]),
    ("provider_run", "needs", []),
    ("provider_run", "needs", "missing"),
    ("provider_run", "needs", "cleanup_on_failure"),
    ("provider_run", "if", "false"),
    ("provider_run", "steps", [{"if": "false", "run": "echo never"}]),
    ("provider_run", "environment", "${{ inputs.environment }}"),
    ("prepare", "environment", "unprotected"),
    ("cleanup", "if", "always()"),
    ("cleanup", "needs", "provider_run"),
])
def test_decoy_unreachable_or_unguarded_job_is_rejected(job, key, wrong):
    doc = example()
    doc["jobs"]["cleanup_on_failure"] = dict(doc["jobs"]["cleanup"], needs="verify_ref")
    doc["jobs"][job][key] = wrong
    with pytest.raises(AssertionError):
        check_boundary(doc)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="M4: decisions/provider-workflow-dispatch.md: Depends on the live provider ports and durable claim. Implement the operator workflow's dispatch structure in .github/workflows/provider-run.yml per decisions/provider-workflow-dispatch.md. Provider wiring requires separate integration evidence.")
def test_provider_workflow_dispatch_boundary():
    assert WORKFLOW.is_file(), "the operator-triggered provider workflow is missing"
    # BaseLoader keeps the event key 'on' as a string.
    check_boundary(yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))
