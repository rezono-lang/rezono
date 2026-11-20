"""One executor applies planned steps, reads back what they changed and records a replayable run."""
from importlib.util import find_spec
import json

import pytest
import yaml

from loop.recording_cli import main
from test_recorded_correction import observation
from test_replay_fixed_point import LOOP, boundary, setup_recording

DECISION = "decisions/loop-apply-readback.md"


class MissingApplyReadbackExecutor(AssertionError):
    """loop/executor.py does not apply a frontier and read back each round."""


class MissingReadbackCompletion(AssertionError):
    """The executor counts a step as done without matching read-back evidence."""


class MissingReadbackFinding(AssertionError):
    """A read-back mismatch is not reported as a drift finding that stops the run."""


class MissingOfflineReplay(AssertionError):
    """The executed run does not replay without a cluster to the same plans and rounds."""


def executor(missing):
    if find_spec("loop.executor") is None:
        raise missing("loop/executor.py does not exist")
    from loop.executor import execute
    return execute


def bootstrap(tmp_path):
    """Two steps from empty: seed has no requirement, ship needs seed's token."""
    data = setup_recording(tmp_path)
    records = data["records"]
    records["loop_step"].append({"id": "seed"})
    records["loop_completion"].append(
        {"id": "seed-definition", "step": "seed", "run": "active", "token": "seeded", "reason": "seed-definition"})
    effect = yaml.safe_load((LOOP.parents[1] / "contracts/fixtures/port/Port/valid/effect.yaml").read_bytes())
    effect.update(name="recorded-apply")
    data["ports"].append(effect)
    return data


class World:
    """A cluster stand-in: apply sets the configured value, read returns one complete dated sweep."""

    def __init__(self, values):
        self.values, self.state, self.applied, self.read_rounds = values, {}, [], []

    def apply(self, run, round, step):
        self.applied.append((run, round, step))
        if step in self.values:
            self.state[step] = self.values[step]
        return "applied"

    def read(self, run, round):
        self.read_rounds.append((run, round))
        sweep = f"round-{round}"
        return boundary(sweep, at=10 + round, observations=[
            observation(run, sweep, step, f"{step}-readback-{round}", 10 + round, value)
            for step, value in sorted(self.state.items())
        ])


def run(tmp_path, missing, values):
    execute = executor(missing)
    data = bootstrap(tmp_path)
    world = World(values)
    report, recording = execute(tmp_path, data, apply=world.apply, read=world.read)
    return data, world, report, recording


@pytest.mark.xfail(
    strict=True,
    raises=MissingApplyReadbackExecutor,
    reason=(
        f"M2: {DECISION}: add loop/executor.py with execute(directory, data, *, apply, read). Each round evaluates "
        "the pinned std-loop pack through the replay path, applies the ready frontier in step-key order, reads one "
        "sweep and evaluates again; it reports plans, outcome, rounds and findings."
    ),
)
def test_executor_applies_then_reads_back(tmp_path):
    _, world, report, _ = run(tmp_path, MissingApplyReadbackExecutor, {"seed": "yes", "ship": "yes"})
    observed = (world.applied, world.read_rounds, report)
    expected = (
        [("active", 1, "seed"), ("active", 2, "ship")],
        [("active", 1), ("active", 2)],
        {"plans": [["seed"], ["ship"]], "outcome": "success", "rounds": 2, "findings": []},
    )
    if observed != expected:
        raise MissingApplyReadbackExecutor(f"{observed!r} is not {expected!r}")


@pytest.mark.xfail(
    strict=True,
    raises=MissingReadbackCompletion,
    reason=(
        f"M2: {DECISION}: in loop/executor.py a step is done only when the pack derives done from matching "
        "read-back evidence; the apply result is never evidence. Waits for test_executor_applies_then_reads_back."
    ),
)
def test_apply_result_is_not_evidence(tmp_path):
    data, world, report, _ = run(tmp_path, MissingReadbackCompletion, {})
    limit = data["limit"]
    observed = (world.applied, report["outcome"], report["plans"], report["rounds"])
    expected = ([("active", r, "seed") for r in range(1, limit + 1)], "failure", [["seed"]] * limit, limit)
    if observed != expected:
        raise MissingReadbackCompletion(f"a silent read-back gave {observed!r}, not {expected!r}")


@pytest.mark.xfail(
    strict=True,
    raises=MissingReadbackFinding,
    reason=(
        f"M2: {DECISION}: in loop/executor.py a read-back value that differs from the expectation is a drift "
        "finding with both references and a failed outcome, and no later step is applied. "
        "Waits for test_executor_applies_then_reads_back."
    ),
)
def test_readback_mismatch_is_a_finding(tmp_path):
    _, world, report, _ = run(tmp_path, MissingReadbackFinding, {"seed": "no", "ship": "yes"})
    observed = (world.applied, report)
    expected = (
        [("active", 1, "seed")],
        {"plans": [["seed"]], "outcome": "failure", "rounds": 1,
         "findings": [{"token": "seeded", "desired": "seeded", "observed": "sweep/round-1/seed-readback-1"}]},
    )
    if observed != expected:
        raise MissingReadbackFinding(f"{observed!r} is not {expected!r}")


@pytest.mark.parametrize("values", [{"seed": "yes", "ship": "yes"}, {"seed": "no"}, {}],
                         ids=["converges", "mismatch", "silent"])
@pytest.mark.xfail(
    strict=True,
    raises=MissingOfflineReplay,
    reason=(
        f"M2: {DECISION}: the recording that loop/executor.py returns is plain JSON and replays with "
        "loop/recording_cli.py, without a cluster, to the same plans, outcome and rounds. "
        "Waits for test_apply_result_is_not_evidence and test_readback_mismatch_is_a_finding."
    ),
)
def test_executed_run_replays_offline(tmp_path, capsys, values):
    data, _, report, recording = run(tmp_path, MissingOfflineReplay, values)
    if json.loads(json.dumps(recording)) != recording or {**recording, "sweeps": []} != {**data, "sweeps": []}:
        raise MissingOfflineReplay("the recording is not the input plus its sweeps as plain JSON")
    if len(recording["sweeps"]) != report["rounds"]:
        raise MissingOfflineReplay("the recording does not hold one sweep per executed round")
    path = tmp_path / "executed.json"
    path.write_text(json.dumps(recording), encoding="utf-8")
    status = main([str(path)])
    replayed = json.loads(capsys.readouterr().out)
    executed = {key: report[key] for key in ("plans", "outcome", "rounds")}
    if {key: replayed[key] for key in executed} != executed or status != (report["outcome"] != "success"):
        raise MissingOfflineReplay(f"the replay gave {replayed!r} with status {status}, not {executed!r}")
