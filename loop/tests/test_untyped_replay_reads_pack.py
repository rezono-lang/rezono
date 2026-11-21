"""An untyped recording is replayed through the std-loop rules: decisions/code-does-not-decide.md."""
import pytest


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
