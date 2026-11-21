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


def test_provider_workflow_dispatch_boundary():
    assert WORKFLOW.is_file(), "the operator-triggered provider workflow is missing"
    # BaseLoader keeps the event key 'on' as a string.
    check_boundary(yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))


def _shell_statements(script):
    import shlex

    joined = script.replace("\\\r\n", " ").replace("\\\n", " ")
    statements = []
    for raw_line in joined.splitlines():
        lexer = shlex.shlex(raw_line, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        current = []
        for token in lexer:
            if token in {";", "&&", "||", "|"}:
                if current:
                    statements.append((current, token))
                    current = []
            else:
                current.append(token)
        if current:
            statements.append((current, ""))
    return statements


def _python_run_entrypoint(tokens, repo_root):
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in {"exec", "env"} or ("=" in tok and tok.split("=", 1)[0].isidentifier()):
            idx += 1
            continue
        break
    if idx >= len(tokens):
        return None
    exe = Path(tokens[idx]).name
    if exe not in {"python", "python3"} and not exe.startswith("python3."):
        return None
    idx += 1
    while idx < len(tokens):
        flag = tokens[idx]
        if flag in {"-I", "-u", "-B", "-E", "-s", "-S", "-O", "-OO", "-P"}:
            idx += 1
        elif flag in {"-W", "-X"}:
            idx += 2
        else:
            break
    if idx >= len(tokens):
        return None
    run_root = (repo_root / "run").resolve()
    if tokens[idx] == "-m" and idx + 1 < len(tokens):
        module = tokens[idx + 1]
        if not module.startswith("run."):
            return None
        parts = module.split(".")
        candidate = (repo_root / Path(*parts)).with_suffix(".py")
        if not candidate.is_file():
            candidate = repo_root / Path(*parts) / "__main__.py"
        resolved = candidate.resolve()
        return resolved if resolved.is_relative_to(run_root) else None
    script = tokens[idx].lstrip("./")
    if script.startswith("run/") and script.endswith(".py"):
        resolved = (repo_root / script).resolve()
        return resolved if resolved.is_relative_to(run_root) else None
    return None


def _resolve_provider_command(doc, repo_root=None):
    check_boundary(doc)
    root = WORKFLOW.parents[2] if repo_root is None else Path(repo_root)
    for step in doc["jobs"]["provider_run"]["steps"]:
        if condition(step) != "success()":
            continue
        script = step.get("run")
        if not isinstance(script, str) or not script.strip():
            continue
        skip_on_and = False
        for tokens, op in _shell_statements(script):
            if skip_on_and:
                skip_on_and = op == "&&"
                continue
            head = tokens[0]
            if head == "exit" and (len(tokens) == 1 or tokens[1] != "0"):
                break
            if head == "false":
                skip_on_and = op == "&&"
                continue
            if head in {"if", "elif", "while", "until"}:
                continue
            target = _python_run_entrypoint(tokens, root)
            if target is not None and target.is_file():
                return target
    raise AssertionError("provider_run job does not invoke a concrete live provider command entrypoint in run/")


def test_provider_workflow_runs_live_command_with_recording_ports(tmp_path):
    import copy
    import subprocess
    from runpy import run_path

    from offline_cases import FIXTURE, PLAN_HASH, RUN, case, implementation

    assert WORKFLOW.is_file(), "the operator-triggered provider workflow is missing"
    doc = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    entrypoint = _resolve_provider_command(doc)

    # Replacing the workflow's command invocation with a no-op or stub must fail closed.
    for noop in ("true", "echo noop", 'echo "python -m run.provider_run"', "exit 1"):
        mutated = copy.deepcopy(doc)
        for step in mutated["jobs"]["provider_run"]["steps"]:
            if condition(step) == "success()" and step.get("run"):
                step["run"] = noop
        with pytest.raises(AssertionError):
            _resolve_provider_command(mutated)

    namespace = run_path(str(entrypoint))
    run_live = namespace.get("run_live")
    assert callable(run_live), f"{entrypoint.name} must expose a callable run_live(...) entrypoint"

    scenario = case()
    execute = run_path(str(RUN.parent / "loop" / "replay.py"))["replay"]
    holder = implementation("git_claim.py", "holder")

    def bare_remote(name):
        remote = tmp_path / name
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        return str(remote)

    def make_ports(inventory_pages):
        calls = {
            "submit_order": [],
            "order_status": [],
            "observe_machines": [],
            "deliver": [],
            "delete_resources": [],
            "list_inventory": [],
        }

        def submit_order(plan_hash, *args, **kwargs):
            calls["submit_order"].append(plan_hash)
            return dict(scenario["order_receipt"])

        def order_status(plan_hash, *args, **kwargs):
            calls["order_status"].append(plan_hash)
            return dict(scenario["order_receipt"])

        def observe_machines(plan_hash, *args, **kwargs):
            calls["observe_machines"].append(plan_hash)
            return copy.deepcopy(scenario["machine_observations"])

        def deliver(plan_hash, *args, **kwargs):
            calls["deliver"].append(plan_hash)
            return dict(scenario["installation"])

        def delete_resources(plan_hash, *args, **kwargs):
            calls["delete_resources"].append(plan_hash)
            return dict(scenario["delete_receipt"])

        def list_inventory(plan_hash, *args, **kwargs):
            calls["list_inventory"].append(plan_hash)
            return copy.deepcopy(inventory_pages)

        ports = {
            "submit_order": submit_order,
            "order_status": order_status,
            "observe_machines": observe_machines,
            "deliver": deliver,
            "delete_resources": delete_resources,
            "list_inventory": list_inventory,
        }
        return ports, calls

    spec = {
        "plan_file": scenario["plan_file"],
        "price_file": scenario["price_file"],
        "request_file": scenario["request_file"],
        "request_sha256": scenario["request_sha256"],
        "approval": copy.deepcopy(scenario["approval"]),
        "clock": scenario["clock"],
    }

    # 1. Approved plan executes a single order through the shared executor with durable Git claim,
    #    performs delivery, and confirms cleanup via complete paginated inventory.
    phases = []

    def observed_execute(*args, **kwargs):
        phases.append(execute(*args, **kwargs))
        return phases[-1]

    remote = bare_remote("claims-live.git")
    ports, calls = make_ports(scenario["inventory"])
    result = run_live(spec, FIXTURE, ports, claim_remote=remote, run_id="live-1", execute=observed_execute)
    assert len(phases) == 2, "live command must run both order and installation phases through the shared executor"
    assert calls["submit_order"] == [PLAN_HASH]
    assert calls["observe_machines"] == [PLAN_HASH]
    assert calls["deliver"] == [PLAN_HASH]
    assert calls["delete_resources"] == [PLAN_HASH]
    assert len(calls["list_inventory"]) >= 1
    assert holder(remote, PLAN_HASH) == "live-1"
    assert result == {
        "plan_hash": PLAN_HASH,
        "cost_micros": 1614000,
        "orders": 1,
        "request": "sample",
        "delivered": True,
        "cleanup": "cleaned",
        "sweep": "after",
        "loop_phases": ["order", "installation"],
        "operations": scenario["operations"],
    }

    # 2. Re-running against the same durable claim remote must not place a second order.
    retry_ports, retry_calls = make_ports(scenario["inventory"])
    restarted = run_live(spec, FIXTURE, retry_ports, claim_remote=remote, run_id="live-2", execute=execute)
    assert retry_calls["submit_order"] == []
    assert len(retry_calls["order_status"]) >= 1
    assert holder(remote, PLAN_HASH) == "live-1"
    assert restarted["orders"] == 0 and restarted["cleanup"] == "cleaned"

    # 3. Incomplete cleanup inventory fails closed as unknown.
    incomplete_remote = bare_remote("claims-incomplete.git")
    incomplete_ports, _ = make_ports(scenario["inventory"][:-1])
    pending = run_live(spec, FIXTURE, incomplete_ports, claim_remote=incomplete_remote, run_id="live-3", execute=execute)
    assert pending["orders"] == 1 and pending["cleanup"] == "unknown"

    # 4. Budget below quote refuses before claiming or ordering.
    refused_remote = bare_remote("claims-refused.git")
    refused_ports, refused_calls = make_ports(scenario["inventory"])
    denied_spec = dict(spec, approval=dict(spec["approval"], budget_cents=161))
    refused = run_live(denied_spec, FIXTURE, refused_ports, claim_remote=refused_remote, run_id="live-4", execute=execute)
    assert refused["orders"] == 0 and refused["delivered"] is False
    assert refused_calls["submit_order"] == []
    assert holder(refused_remote, PLAN_HASH) is None
