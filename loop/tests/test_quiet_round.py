"""A quiet sweep can advance a deadline or prove a fixed point without changing a token."""
import json
import shutil

import pytest
import yaml

from pack_records import LOOP, evaluate
from wire_fixtures import ROOT, entry


RUN = "current"


def event(key, token, value, at, run=RUN):
    return {"id": key, "run": run, "token": token, "state": "known",
            "value": value, "event_time": at, "reason": key}


def sweep(key, run, at, complete):
    return {"id": key, "run": run, "event_time": at, "complete": complete}


def scenario(at=14, *, complete=True, pending=True, producer=False, permit=False,
             finished=False, expected=False, observed="deny", start_run=RUN, done_at=13):
    data = {
        "loop_active_run": [{"id": RUN}],
        "loop_step": [{"id": "publish"}],
        "loop_completion": [{"id": "completion", "run": RUN, "step": "publish",
                             "token": "released", "reason": "completion"}],
        "loop_requirement": [{"id": "requirement", "run": RUN, "step": "publish",
                              "token": "permit", "reason": "requirement"}],
        "loop_expectation": [{"id": k, "value": v} for k, v in
                             (("started", "yes"), ("permit", "yes"), ("released", "yes"), ("probe", "allow"))],
        "loop_observation": [event("start", "started", "yes", 10, start_run)],
        "loop_deadline": [{"id": "deadline", "run": RUN, "step": "publish", "start": "start", "budget": 5}],
        "loop_sweep": [sweep("foreign", "earlier-run", 90, True)],
        "loop_pending_operation": [],
        "loop_expected_difference": [],
    }
    if at is not None:
        data["loop_sweep"].append(sweep("quiet", RUN, at, complete))
    if pending:
        data["loop_pending_operation"].append({"id": "in-flight", "run": RUN, "token": "permit"})
    if producer:
        data["loop_step"].append({"id": "supply"})
        data["loop_completion"].append({"id": "supply-def", "run": RUN, "step": "supply",
                                        "token": "permit", "reason": "supply-def"})
    if permit:
        data["loop_observation"].append(event("approved", "permit", "yes", 12))
    if finished:
        data["loop_observation"] += [event("published", "released", "yes", done_at),
                                     event("probe-reading", "probe", observed, done_at)]
    if expected:
        data["loop_expected_difference"].append({"id": "drill", "run": RUN, "token": "probe", "observed": "deny"})
    return data


# Hand-calculated from decisions/quiet-observation-rounds.md. Columns give the
# ready flag for publish, blocking evidence IDs, terminal state, and probe finding.
CASES = [
    ({}, False, (), "pending", False),
    ({"at": None, "pending": False}, False, (), "pending", False),
    ({"complete": False, "pending": False}, False, (), "pending", False),
    ({"pending": False}, False, ("quiet", "requirement"), "failure", False),
    ({"pending": False, "producer": True}, False, (), "pending", False),
    ({"permit": True, "pending": False}, True, (), "pending", False),
    ({"at": 15, "permit": True, "pending": False}, False, ("quiet", "deadline", "start"), "failure", False),
    ({"at": 15}, False, ("quiet", "deadline", "start"), "failure", False),
    ({"at": 16, "finished": True, "permit": True, "expected": True}, False, (), "success", True),
    ({"at": 16, "finished": True, "permit": True}, False, (), "failure", True),
    ({"at": 16, "finished": True, "permit": True, "expected": True, "observed": "refused"},
     False, (), "failure", True),
    # An incomplete sweep still dates the round, so it expires the deadline at the boundary.
    ({"at": 15, "complete": False}, False, ("quiet", "deadline", "start"), "failure", False),
    # Expiry is terminal: a completion observed after the boundary does not clear it.
    ({"at": 16, "finished": True, "permit": True, "expected": True, "done_at": 16},
     False, ("quiet", "deadline", "start"), "failure", True),
    # A completion observed at the boundary is in time.
    ({"at": 16, "finished": True, "permit": True, "expected": True, "done_at": 15}, False, (), "success", True),
    # A start observation of another run never dates the deadline; the invariant reports it instead.
    ({"at": 15, "start_run": "earlier-run"}, False, (), "pending", False),
]


def foreign_starts(data):
    runs = {o["id"]: o["run"] for o in data["loop_observation"]}
    return {(d["id"],) for d in data["loop_deadline"] if runs.get(d["start"], d["run"]) != d["run"]}


def reference(data):
    # One required token and at most one potential producer in this finite fixture.
    seen = {o["token"]: o for o in data["loop_observation"] if o["run"] == RUN}
    latest = max((s for s in data["loop_sweep"] if s["run"] == RUN), key=lambda s: s["event_time"], default=None)
    deadline, = data["loop_deadline"]
    start = next(o for o in data["loop_observation"] if o["id"] == deadline["start"])
    until = start["event_time"] + deadline["budget"]
    done = seen.get("released", {}).get("value") == "yes"
    in_time = done and seen["released"]["event_time"] <= until
    permit = seen.get("permit", {}).get("value") == "yes"
    producer = any(c["run"] == RUN and c["token"] == "permit" for c in data["loop_completion"])
    pending = any(c["run"] == RUN and c["token"] == "permit" for c in data["loop_pending_operation"])
    blockers = ()
    if latest and done and not in_time and start["run"] == RUN and latest["event_time"] >= until:
        blockers = (latest["id"], deadline["id"], start["id"])
    if latest and not done:
        if start["run"] == RUN and latest["event_time"] >= until:
            blockers = (latest["id"], deadline["id"], start["id"])
        elif latest["complete"] and not (permit or producer or pending):
            blockers = (latest["id"], data["loop_requirement"][0]["id"])
    reading = seen.get("probe", {}).get("value")
    drift = reading is not None and reading != "allow"
    excused = any(d["run"] == RUN and d["token"] == "probe" and d["observed"] == reading
                  for d in data["loop_expected_difference"])
    state = "failure" if blockers or (drift and not excused) else "success" if done else "pending"
    return permit and not done and not blockers, blockers, state, drift


def test_quiet_round_reference():
    for settings, ready, proof, outcome, drift in CASES:
        assert reference(scenario(**settings)) == (ready, proof, outcome, drift)
    assert [s for s, *_ in CASES if foreign_starts(scenario(**s))] == [{"at": 15, "start_run": "earlier-run"}]


def ground_ids(program, explainer, relation, row):
    proof = explainer.proof(relation, row, "fixture")
    ids = set()
    for witness in proof["witnesses"]:
        for p in witness["premises"]:
            if p["polarity"] == "positive" and p["row"]["relation"] in program.base_used():
                key = json.loads(p["row"]["key"])
                if key:
                    ids.add(key[0])
    return ids


def test_quiet_round_rules():
    from rezono_compiler import pack

    model = pack.read(LOOP)
    for settings, *_ in CASES:
        records = scenario(**settings)
        ready, proof, outcome, drift = reference(records)
        program, rows, explainer = evaluate(model, records)
        assert any(row[:2] == (RUN, "publish") for row in rows["ready"]) is ready
        blocked = [row for row in rows["stuck"] if row[:2] == (RUN, "publish")]
        assert bool(blocked) is bool(proof)
        if blocked:
            assert any(set(proof) <= ground_ids(program, explainer, "stuck", row) for row in blocked)
        assert rows["round_outcome"] == {(RUN, outcome)}
        assert rows["deadline_foreign_start"] == foreign_starts(records)
        findings = [row for row in rows["drift"] if row[:2] == (RUN, "probe")]
        assert bool(findings) is drift
        if findings:
            assert any({"probe", "probe-reading"} <= ground_ids(program, explainer, "drift", row) for row in findings)


def test_quiet_round_recording(monkeypatch, tmp_path, capsys):
    from rezono_compiler import batch, modules

    main = entry(monkeypatch, "recording_cli", "main")
    for name in ("std-order", "std-loop"):
        shutil.copytree(LOOP.parent / name, tmp_path / name)
    ports = ROOT.parent / "contracts" / "fixtures" / "port" / "Port" / "valid"
    reader = yaml.safe_load((ports / "in.yaml").read_text(encoding="utf-8"))
    reader.update(name="recorded-status", consumes=["loop_step"], produces=["loop_observation"], secrets=[])
    effect = yaml.safe_load((ports / "effect.yaml").read_text(encoding="utf-8"))
    effect.update(name="recorded-effect", consumes=["loop_step"], produces=["loop_completion"])
    recording = {"run": RUN, "limit": 3, "ports": [reader, effect], "initial": [],
                 "pack": {"path": "std-loop", "sha256": modules.pack_hash(tmp_path / "std-loop")},
                 "records": scenario(at=None), "sweeps": [
                     dict(sweep("before", RUN, 14, False), observations=[]),
                     dict(sweep("at-boundary", RUN, 15, True), observations=[]),
                 ]}
    path = tmp_path / "quiet.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    snapshots = []
    calculate = batch.compute

    def capture(con, program, *args, **kwargs):
        result = calculate(con, program, *args, **kwargs)
        if {"stuck", "round_outcome"} <= set(program.derived()):
            snapshots.append(batch.read(con, program, ["loop_sweep__event_time", "stuck", "round_outcome"]))
        return result

    monkeypatch.setattr(batch, "compute", capture)
    assert main([str(path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert (report["plans"], report["rounds"], report["outcome"]) == ([[], []], 2, "failure")
    before = next(i for i, s in enumerate(snapshots) if ("before", "14") in s["loop_sweep__event_time"]
                  and ("at-boundary", "15") not in s["loop_sweep__event_time"])
    assert snapshots[before]["round_outcome"] == {(RUN, "pending")}
    final = snapshots[-1]
    assert before < len(snapshots) - 1 and ("at-boundary", "15") in final["loop_sweep__event_time"]
    assert final["round_outcome"] == {(RUN, "failure")}
    assert any(row[:2] == (RUN, "publish") for row in final["stuck"])
