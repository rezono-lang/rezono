"""Platform startup, retirement and restore steps are std-loop rows (decisions/standard-packs-everywhere.md,
section 2).

The cases are the ones this file held for rules/safe_step.dl, and those of test_restore_offline_dependencies.py,
in the terms of std-loop (decisions/loop-certificate-admission.md, decisions/safe-step-rounds.md section 1). A step
waits while a token it needs is not known in its own run. A token is known from the latest reading of the run
with the expected value; equal-time readings that disagree give none. A refuted or unknown step check at the
current cut blocks. A done step cites the reading that confirmed its completion token.
"""

from copy import deepcopy
from hashlib import sha256

import pytest

from case_support import ROOT, verified
from management_probes import compiled
from rezono_compiler import pack, rules

SAFE_STEP_KINDS = {"safe_round_cut", "safe_step_request", "safe_step_observation", "safe_step_scope"}
LOOP_INPUTS = {"loop_active_run", "loop_sweep_receipt", "loop_step", "loop_requirement", "loop_expectation",
               "loop_observation", "loop_completion", "loop_step_safety_check"}
LOOP_RELATIONS = {"known", "current", "waiting", "unblocked", "done", "step_safety_blocker"}


def observe(run, cut, evidence, reader, token, value, time=9):
    return {"id": evidence, "run": run, "token": token, "event_time": time, "state": "known", "value": value,
            "reason": evidence, "scope": reader, "sweep": cut}


def of_run(state, relation, run):
    return {row for row in state.derived.get(relation, ()) if row[0] == run}


def tokens(state, relation, run, token):
    return {row for row in of_run(state, relation, run) if row[1] == token}


def test_startup_transition_cases():
    assert not (ROOT / "rules" / "safe_step.dl").exists(), "rules/safe_step.dl rebuilds std-loop's step safety"
    assert not (ROOT / "schema" / "safe_step.yaml").exists(), "schema/safe_step.yaml rebuilds std-loop's inputs"
    model = pack.read(ROOT)
    assert not SAFE_STEP_KINDS & set(model.kinds), f"Platform kinds beside std-loop: {sorted(SAFE_STEP_KINDS & set(model.kinds))}"
    assert LOOP_INPUTS <= set(model.kinds), f"Missing std-loop input kinds: {sorted(LOOP_INPUTS - set(model.kinds))}"
    derived = set(rules.load(model.rules).derived())
    assert "startup_transition_result" not in derived, "The platform still derives its own step verdicts"
    assert LOOP_RELATIONS <= derived, f"Missing std-loop relations: {sorted(LOOP_RELATIONS - derived)}"

    # Startup: expose the entry listener, and retire the identity database while identity may still run on it.
    run, cut = "startup-case", "current-cut"
    expose, retire = "expose-entry", "retire-database"
    policy, router, consumer = "lb/network-policy", "lb/router-policy", "idp/runtime"
    records = {
        "loop_active_run": [{"id": run}],
        "loop_sweep_receipt": [{"id": cut, "run": run, "event_time": 10},
                               {"id": "older-cut", "run": run, "event_time": 5}],
        "loop_step": [{"id": expose}, {"id": retire}],
        "loop_requirement": [
            {"id": "expose-policy", "run": run, "step": expose, "token": policy, "reason": "effective-protection"},
            {"id": "expose-router", "run": run, "step": expose, "token": router, "reason": "effective-protection"},
            {"id": "retire-consumer", "run": run, "step": retire, "token": consumer, "reason": "identity-database"},
        ],
        "loop_expectation": [{"id": policy, "value": "effective"}, {"id": router, "value": "effective"},
                             {"id": consumer, "value": "stopped"}],
        "loop_observation": [
            observe(run, cut, "network-policy", "policy", policy, "effective"),
            observe(run, cut, "identity-state", "runtime", consumer, "running"),
            observe(run, cut, "other-router-allowance", "router", "another-listener/router-policy", "effective"),
            observe("previous-run", "previous-cut", "earlier-stop", "runtime", consumer, "stopped", time=12),
        ],
    }
    model, state = compiled(records)
    # No router allowance for the entry is read: the exposure waits, unknown rather than refuted. Identity runs on
    # the database in this run: the retirement waits, and the contrary value is current. A stop recorded by
    # another run, even a later one, counts for nothing here.
    assert of_run(state, "waiting", run) == {(run, expose, router, "effective-protection"),
                                              (run, retire, consumer, "identity-database")}
    assert not tokens(state, "current", run, router)
    assert (run, consumer, "known", "running", "identity-state") in state.derived.get("current", ())
    assert not {row[1] for row in of_run(state, "unblocked", run)} & {expose, retire}
    assert ("loop_requirement__token", ("retire-consumer", consumer)) in verified(
        "waiting", (run, retire, consumer, "identity-database"), state=(model, state))
    assert ("loop_observation__value", ("identity-state", "running")) in verified(
        "current", (run, consumer, "known", "running", "identity-state"), state=(model, state))

    # The certifier's results enter as step checks. Only those of the current cut count: a refutation at an older
    # cut blocks nothing, missing router coverage at the current one leaves the exposure unknown.
    checked = deepcopy(records)
    checked["loop_step_safety_check"] = [
        {"id": "old-refutation", "run": run, "step": expose, "cut": "older-cut", "obligation": "router-coverage",
         "verdict": "refuted", "reason": "violated-invariant"},
        {"id": "router-coverage", "run": run, "step": expose, "cut": cut, "obligation": "router-coverage",
         "verdict": "unknown", "reason": "missing-coverage"},
    ]
    _, state = compiled(checked)
    assert (run, expose, "router-coverage", "missing-coverage") in of_run(state, "waiting", run)
    assert (run, expose, "router-coverage", "violated-invariant") not in of_run(state, "waiting", run)

    # With the router allowance read and identity stopped, both steps are free of waiting rows.
    safe = deepcopy(records)
    safe["loop_observation"].append(observe(run, cut, "router-allowance", "router", router, "effective"))
    safe["loop_observation"][1]["value"] = "stopped"
    model, state = compiled(safe)
    assert not of_run(state, "waiting", run)
    assert {(run, expose, expose), (run, retire, retire)} <= of_run(state, "unblocked", run)
    assert {(run, policy, "network-policy"), (run, router, "router-allowance"),
            (run, consumer, "identity-state")} <= of_run(state, "known", run)
    assert {("loop_observation__value", ("router-allowance", "effective")),
            ("loop_expectation__value", (router, "effective"))} <= verified(
        "known", (run, router, "router-allowance"), state=(model, state))

    # A contradictory reading at the same time leaves the protection unknown: no token and no current value.
    contradicted = deepcopy(safe)
    contradicted["loop_observation"].append(observe(run, cut, "router-denial", "router", router, "denied"))
    _, state = compiled(contradicted)
    assert of_run(state, "waiting", run) == {(run, expose, router, "effective-protection")}
    assert not tokens(state, "known", run, router) and not tokens(state, "current", run, router)

    # Router allowance without any network-policy read leaves the protection unknown.
    unread = deepcopy(safe)
    unread["loop_observation"].pop(0)
    _, state = compiled(unread)
    assert of_run(state, "waiting", run) == {(run, expose, policy, "effective-protection")}
    assert not tokens(state, "current", run, policy)

    # Restore: the trial's dependencies are readings of the restore run, and the matching readback confirms the
    # restore step's completion token.
    run, cut, step = "restore-run", "offline-cut", "restore-copy"
    digest = sha256(b"authored recovery payload\n").hexdigest()
    payload = "chosen-copy/payload"
    bindings = (("control", "recovery-api"), ("credentials", "recovery-key"), ("storage", "backup-store"))
    restore = {
        "loop_active_run": [{"id": run}],
        "loop_sweep_receipt": [{"id": cut, "run": run, "event_time": 20}],
        "loop_step": [{"id": step}],
        "loop_requirement": [{"id": f"needs-{function}", "run": run, "step": step,
                              "token": f"{provider}/availability", "reason": function}
                             for function, provider in bindings],
        "loop_completion": [{"id": "restored-copy", "run": run, "step": step, "token": payload,
                             "reason": "matching-copy"}],
        "loop_expectation": [{"id": f"{provider}/availability", "value": "available"} for _, provider in bindings]
        + [{"id": payload, "value": digest}],
        "loop_observation": [observe(run, cut, f"observed-{function}", function, f"{provider}/availability",
                                     "available", time=18) for function, provider in bindings],
    }
    _, state = compiled(restore)
    assert not of_run(state, "waiting", run)
    assert (run, step, step) in of_run(state, "unblocked", run)
    assert not of_run(state, "done", run)

    readback = observe(run, cut, "readback", "recovery", payload, digest, time=19)
    finished = deepcopy(restore)
    finished["loop_observation"].append(readback)
    model, state = compiled(finished)
    assert of_run(state, "done", run) == {(run, step, "readback")}
    assert ("loop_observation__value", ("readback", digest)) in verified(
        "done", (run, step, "readback"), state=(model, state))

    # Wrong bytes do not complete the restore.
    wrong = deepcopy(finished)
    wrong["loop_observation"][-1]["value"] = sha256(b"different recovery payload\n").hexdigest()
    _, state = compiled(wrong)
    assert not of_run(state, "done", run)

    # A reading from another run is no reading of this one.
    missing = deepcopy(restore)
    missing["loop_observation"][1]["run"] = "previous-run"
    _, state = compiled(missing)
    assert of_run(state, "waiting", run) == {(run, step, "recovery-key/availability", "credentials")}

    # A later reading that contradicts an earlier one is the current value: the control plane is unavailable.
    later = deepcopy(restore)
    later["loop_observation"].append(observe(run, cut, "observed-control-later", "control", "recovery-api/availability",
                                             "unavailable", time=19))
    _, state = compiled(later)
    assert of_run(state, "waiting", run) == {(run, step, "recovery-api/availability", "control")}
    assert (run, "recovery-api/availability", "known", "unavailable", "observed-control-later") in state.derived.get(
        "current", ())

    # A dependency on the unavailable management cluster violates the platform's offline invariant; the certifier
    # reports it at the current cut and the step waits on it.
    dependent = deepcopy(restore)
    dependent["loop_step_safety_check"] = [{"id": "management-dependent", "run": run, "step": step, "cut": cut,
                                            "obligation": "recovery-api/offline", "verdict": "refuted",
                                            "reason": "violated-invariant"}]
    _, state = compiled(dependent)
    assert of_run(state, "waiting", run) == {(run, step, "recovery-api/offline", "violated-invariant")}
