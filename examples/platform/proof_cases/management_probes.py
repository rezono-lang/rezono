"""Exercise platform rules on caller-supplied facts and read the live loop recorder in the fixture."""

import json
import os
from pathlib import Path
import subprocess

from case_support import ROOT
from rezono_compiler import calc, facts, pack, rules
from rules_support import State


def compiled(records):
    model = pack.read(ROOT)
    assert set(records) <= set(model.kinds), f"Missing management input kinds: {sorted(records.keys() - set(model.kinds))}"
    program = rules.load(model.rules)
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    return model, State(model, program, "management", facts.rows_of(model, records), calculation)


def live_events(feature):
    """Read this Actions attempt's completed recorder Job logs via its Pod owner UID."""
    run = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    assert run.isdecimal() and attempt.isdecimal(), "Requires the real disposable workflow run"
    assert os.environ.get("REZONO_CLUSTER_KUBECONFIG") and os.environ.get("RUNNER_TEMP"), "Requires the dedicated fixture kubeconfig"
    config = Path(os.environ["REZONO_CLUSTER_KUBECONFIG"]).resolve(strict=True)
    assert config.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True))
    command = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
    def read(*args):
        return subprocess.check_output([*command, *args], text=True, timeout=25)
    assert read("config", "current-context").strip() == "kind-rezono-fixture"
    command.extend(["--context", "kind-rezono-fixture", "-n", "rezono-probes"])
    name = f"record-{feature}-{run}-{attempt}"
    job = json.loads(read("get", "job", name, "-o", "json"))
    assert job["status"]["succeeded"] == 1
    pods = json.loads(read("get", "pods", "-l", f"job-name={name}", "-o", "json"))["items"]
    pod, = [p for p in pods if p["status"]["phase"] == "Succeeded"
            and any(o["uid"] == job["metadata"]["uid"] and o["controller"] for o in p["metadata"]["ownerReferences"])]
    events = [json.loads(line) for line in read("logs", pod["metadata"]["name"], "-c", "recorder").splitlines()]
    assert events and all(e["run"] == run and e["attempt"] == attempt and e["feature"] == feature for e in events)
    assert all(e["evidence"] and e["observed_at"] for e in events)
    return events
