"""Read the dedicated provider workflow as data. Never invoke its steps."""
from copy import deepcopy
from pathlib import Path
import re

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/provider-run.yml"
MAIN = "github.ref == 'refs/heads/main'"
VERIFY_REF = 'test "$GITHUB_REF" = refs/heads/main'


def check_workflow(doc):
    triggers = doc["on"]
    if isinstance(triggers, dict):
        assert set(triggers) == {"workflow_dispatch"}
        options = triggers["workflow_dispatch"]
        assert options in ("", None) or (isinstance(options, dict) and options.keys() <= {"inputs"})
    else:
        assert triggers in ("workflow_dispatch", ["workflow_dispatch"])

    assert len(doc["jobs"]) == 1
    job, = doc["jobs"].values()
    assert not {"needs", "strategy", "uses"} & job.keys()
    assert job.get("runs-on")
    condition = job.get("if", "").strip()
    if condition.startswith("${{") and condition.endswith("}}"):
        condition = condition[3:-2].strip()
    assert re.fullmatch(r"github\.ref\s*==\s*'refs/heads/main'", condition)
    env = job.get("environment")
    assert (env.get("name") if isinstance(env, dict) else env) == "provider-run"

    first, *remaining = job["steps"]
    assert first["shell"] == "sh" and first["run"].strip() == VERIFY_REF
    assert first.keys() <= {"name", "id", "shell", "run"}
    assert all(step.get("if", "success()") == "success()" for step in remaining)
    entries = [step for step in remaining if step.get("id") == "provider_run"]
    assert len(entries) == 1
    entry, = entries
    commands = [entry[key] for key in ("run", "uses") if key in entry]
    assert len(commands) == 1 and isinstance(commands[0], str) and commands[0].strip()


def example():
    return {"on": {"workflow_dispatch": {}}, "jobs": {"apply": {
        "runs-on": "ubuntu-24.04", "environment": "provider-run", "if": MAIN,
        "steps": [{"shell": "sh", "run": VERIFY_REF},
                  {"id": "provider_run", "run": "echo synthetic"}],
    }}}


@pytest.mark.parametrize("triggers", ["workflow_dispatch", ["workflow_dispatch"], {"workflow_dispatch": {}}])
def test_manual_workflow_shapes(triggers):
    doc = example()
    doc["on"] = triggers
    doc["jobs"]["apply"]["environment"] = {"name": "provider-run"}
    doc["jobs"]["apply"]["if"] = "${{ " + MAIN + " }}"
    check_workflow(doc)


@pytest.mark.parametrize(("key", "wrong"), [
    ("if", "false"),
    ("if", "startsWith(github.ref, 'refs/heads/main')"),
    ("if", MAIN + " || github.ref_type == 'tag'"),
    ("if", "github.ref_name == 'main'"),
    ("environment", "preflight"),
    ("environment", "${{ inputs.environment }}"),
    ("needs", "unreachable"),
])
def test_bad_provider_job_is_rejected(key, wrong):
    doc = example()
    doc["jobs"]["apply"][key] = wrong
    with pytest.raises(AssertionError):
        check_workflow(doc)


def test_dispatch_branch_filter_cannot_replace_the_job_guard():
    doc = example()
    doc["on"]["workflow_dispatch"] = {"branches": ["main"]}
    with pytest.raises(AssertionError):
        check_workflow(doc)


def test_decoy_guard_is_rejected():
    doc = example()
    decoy = deepcopy(doc["jobs"]["apply"])
    del doc["jobs"]["apply"]["if"]
    doc["jobs"]["check"] = decoy
    with pytest.raises(AssertionError):
        check_workflow(doc)


@pytest.mark.parametrize("other", ["push", "pull_request", "workflow_call", "schedule"])
def test_extra_trigger_is_rejected(other):
    doc = example()
    doc["on"][other] = {}
    with pytest.raises(AssertionError):
        check_workflow(doc)


@pytest.mark.parametrize(("step", "field", "wrong"), [
    (0, "continue-on-error", True),
    (0, "run", 'test "$GITHUB_REF_NAME" = main'),
    (1, "if", "false"),
    (1, "if", "always()"),
    (1, "run", ""),
    (1, "id", "decoy"),
])
def test_unreachable_or_unguarded_steps_are_rejected(step, field, wrong):
    doc = example()
    doc["jobs"]["apply"]["steps"][step][field] = wrong
    with pytest.raises(AssertionError):
        check_workflow(doc)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Depends on the live provider ports and durable claim. Wire .github/workflows/provider-run.yml per decisions/provider-workflow-dispatch.md once those ports exist.")
def test_provider_workflow_dispatch_boundary():
    assert WORKFLOW.is_file(), "the operator-triggered provider workflow is missing"
    # BaseLoader preserves the GitHub event key 'on' as a string.
    check_workflow(yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))
