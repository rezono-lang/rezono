"""A round outcome comes from the std-loop rule, never from Python: decisions/code-does-not-decide.md."""
import pytest


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
