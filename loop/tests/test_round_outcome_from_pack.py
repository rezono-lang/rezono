"""A round outcome comes from the std-loop rule, never from Python: decisions/code-does-not-decide.md."""
import pytest


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/code-does-not-decide.md, row loop/round_outcome.py. packs/std-loop/rules/round_outcome.dl "
        "decides success, pending and failure; loop/replay.py may not fall back to loop.round_outcome.outcome. "
        "Add round_outcome to RELATIONS in loop/typed_recording.py, so a pinned pack without it is refused, and "
        "make replay_report raise ValueError naming the missing round outcome for a snapshot whose round_outcome "
        "is None. Lands with loop/tests/test_untyped_replay_reads_pack.py: until replay() reads the pack, an "
        "untyped recording has no outcome, and loop/tests/test_replay.py, test_recording_cli.py and "
        "run/tests/test_offline_run.py must stay green. Today RELATIONS lacks round_outcome (AssertionError)."
    ),
)
def test_round_outcome_comes_from_the_pack(monkeypatch):
    import loop.replay as replay_module
    from loop.replay import Snapshot, replay_report
    from loop.typed_recording import RELATIONS

    assert "round_outcome" in RELATIONS, "a typed recording must require round_outcome from its pinned pack"

    def forbidden(**_):
        raise AssertionError("Python decided the round outcome")

    monkeypatch.setattr(replay_module, "outcome", forbidden, raising=False)
    decided = Snapshot({"seed"}, [], {"seed"}, set(), (), round_outcome="success")
    assert replay_report("r", 1, iter([decided]), report_limit=True) == ([], "success", [])
    undecided = Snapshot({"seed"}, [], {"seed"}, set(), ())
    with pytest.raises(ValueError, match="round outcome"):
        replay_report("r", 1, iter([undecided]), report_limit=True)
