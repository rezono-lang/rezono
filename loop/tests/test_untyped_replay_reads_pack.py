"""An untyped recording is replayed through the std-loop rules: decisions/code-does-not-decide.md."""
import pytest


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/code-does-not-decide.md, row loop/replay.py. replay() computes known, done and ready of "
        "an untyped recording in Python (loop/replay.py lines 55 to 77) and takes its outcome from "
        "loop.round_outcome. Read the requirements, completion tokens and evidence as std-loop records "
        "(loop_step, loop_requirement, loop_completion, loop_expectation, loop_observation, as "
        "loop/typed_recording.py admits them) and read done, round_outcome and the frontier relation of "
        "packs/std-loop (ready, or unblocked once loop/tests/test_ready_requires_checked_batch_member.py has "
        "switched its readers) through rezono_compiler.batch.read for every sweep. The answer stays the "
        "hand-calculated one of "
        "loop/tests/test_replay.py. Lands with loop/tests/test_round_outcome_from_pack.py. Today replay() calls "
        "the Python outcome (AssertionError)."
    ),
)
def test_untyped_replay_reads_the_loop_pack(monkeypatch):
    from rezono_compiler import batch

    import loop.replay as replay_module

    seen = set()
    read = batch.read

    def spy(con, prog, names=None):
        rows = read(con, prog, names)
        seen.update((prog.pack, name) for name in rows)
        return rows

    def forbidden(**_):
        raise AssertionError("Python decided the round outcome")

    monkeypatch.setattr(batch, "read", spy)
    monkeypatch.setattr(replay_module, "outcome", forbidden, raising=False)
    requirements = {"build": [], "serve": ["artifact"]}
    completion = {"build": "artifact", "serve": "available"}
    sweeps = [[("r", "artifact", "built")], [("r", "available", "up")]]
    observed = [("prior", "artifact", "old-artifact")]
    assert replay_module.replay("r", requirements, completion, observed, sweeps, 2) == (
        [["build"], ["serve"]], "success")
    assert {("std-loop", "done"), ("std-loop", "round_outcome")} <= seen, sorted(seen)
    assert seen & {("std-loop", "ready"), ("std-loop", "unblocked")}, sorted(seen)
