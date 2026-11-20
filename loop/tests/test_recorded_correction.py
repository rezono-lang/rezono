"""An event-time correction must reach the same evaluator that chooses the plans."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from wire_fixtures import ROOT, entry


def observation(run, sweep, step, position, second, value):
    token = {"seed": "seeded", "ship": "shipped"}[step]
    return {
        "run": run, "sweep": sweep, "port": "recorded-status", "reason": f"sweep/{sweep}/{position}",
        "observation": {
            "id": f"recorded-status/{position}", "subject": step, "attribute": "status",
            "value": {"state": "known", "value": value},
            "event_time": f"2026-01-01T00:00:{second:02d}Z",
            "source": {"kind": "tool", "name": "recorded-status", "position": position},
            "expectation": {"relation": "loop_expectation__value", "key": json.dumps([token])},
        },
    }


def test_recorded_correction(monkeypatch, tmp_path, capsys):
    from rezono_compiler import batch, modules, pack

    snapshots = []
    relations = {"needed", "known", "waiting", "unblocked", "done", "stuck"}
    compute = batch.compute

    def observe_compute(connection, program, *args, **kwargs):
        result = compute(connection, program, *args, **kwargs)
        if relations <= set(program.derived()):
            snapshots.append(batch.read(connection, program, sorted(relations)))
        return result

    monkeypatch.setattr(batch, "compute", observe_compute)
    main = entry(monkeypatch, "recording_cli", "main")
    packs = ROOT.parent / "packs"
    for name in ("std-order", "std-loop"):
        shutil.copytree(packs / name, tmp_path / name)
    theory = tmp_path / "std-loop"
    ports = ROOT.parent / "contracts" / "fixtures" / "port" / "Port" / "valid"
    reader = yaml.safe_load((ports / "in.yaml").read_text(encoding="utf-8"))
    reader.update(name="recorded-status", consumes=["loop_step"], produces=["loop_observation"], secrets=[])
    effect = yaml.safe_load((ports / "effect.yaml").read_text(encoding="utf-8"))
    effect.update(name="recorded-effect", consumes=["loop_step"], produces=["loop_completion"])
    confirmed = observation("active", "first", "seed", "first-seed", 10, "yes")
    shipped = observation("active", "last", "ship", "ship", 11, "yes")
    foreign = observation("other", "last", "seed", "foreign", 59, "yes")
    recording = {
        "run": "active", "limit": 2, "ports": [reader, effect],
        "pack": {"path": "std-loop", "sha256": modules.pack_hash(theory)},
        "records": {
            "loop_active_run": [{"id": "active"}],
            "loop_step": [{"id": "seed", "precedes": ["ship"]}, {"id": "ship"}],
            "loop_completion": [
                {"id": f"completion-{step}", "run": "active", "step": step, "token": token, "reason": f"def-{step}"}
                for step, token in (("seed", "seeded"), ("ship", "shipped"))
            ],
            "loop_expectation": [{"id": "seeded", "value": "yes"}, {"id": "shipped", "value": "yes"}],
        },
        "initial": [], "sweeps": [],
    }
    path = tmp_path / "recording.json"

    def run(second):
        correction = observation("active", "last", "seed", "correction", second, "no")
        recording["sweeps"] = [[confirmed], [shipped, correction, foreign]]
        path.write_text(json.dumps(recording), encoding="utf-8")
        status = main([str(path)])
        return status, json.loads(capsys.readouterr().out)

    for second, expected_status, expected_outcome in ((2, 0, "success"), (12, 1, "failure")):
        snapshots.clear()
        status, report = run(second)
        assert (status, report["plans"], report["outcome"], report["rounds"]) == (
            expected_status, [["seed"], ["ship"]], expected_outcome, 2)

        frontiers = [{row[1] for row in state["unblocked"] if row[0] == "active"} for state in snapshots]
        assert {"seed"} in frontiers and {"ship"} in frontiers[frontiers.index({"seed"}) + 1:]
        final = snapshots[-1]
        completed = {row[1] for row in final["done"] if row[0] == "active"}
        assert completed == ({"seed", "ship"} if second == 2 else {"ship"})
        assert ("active", "shipped", "sweep/last/ship") in final["known"]

    # Change only the rules of the theory read from the pinned path. Both steps now derive done even before
    # the first sweep. Changed bytes cannot carry the name std-loop (decisions/standard-pack-names.md) and the
    # replay requires std-loop, so the changed rules come from an ordinary copy. A replay that took its
    # theory from anywhere but the pinned path would not see them.
    control = tmp_path / "loop-control"
    shutil.copytree(theory, control)
    meta = yaml.safe_load((control / "pack.yaml").read_text(encoding="utf-8")) | {"name": "loop-control"}
    (control / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    done = control / "rules" / "done.dl"
    with done.open("a", encoding="utf-8") as stream:
        stream.write('\ndone(r, "seed", "control-seed") :- active(r).\n')
        stream.write('done(r, "ship", "control-ship") :- active(r).\n')
    read = pack.read
    changed = read(control).rules

    def read_pinned(directory):
        model = read(directory)
        if Path(directory).resolve() == theory.resolve():
            model.rules = changed
        return model

    monkeypatch.setattr(pack, "read", read_pinned)
    status, report = run(2)
    assert (status, report["plans"], report["outcome"]) == (0, [], "success")
