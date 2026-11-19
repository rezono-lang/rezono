"""During transition, run the Python selection and record each disagreement with the pack."""
from importlib.util import find_spec

import pytest

UNIVERSE = frozenset({"alpha", "beta", "gamma", "viewer"})


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: Read decisions/build-reconciliation.md, section Transition evidence. Add loop/build_transition_choice.py "
        "with transition_choice(*, run, pack, python, universe) that keeps the Python result, records a "
        "disagreement with both sides, and requests every suite when the pack result is unverified. "
        "Write only in that file."
    ),
)
def test_build_transition_choice():
    assert find_spec("loop.build_transition_choice") is not None, "The build transition choice is missing"
    from loop.build_transition_choice import transition_choice

    agreed = transition_choice(run="current", pack=frozenset({"beta", "alpha"}), python=frozenset({"alpha", "beta"}),
                               universe=UNIVERSE)
    assert agreed == {"run": "current", "use": ["alpha", "beta"], "source": "agreed", "disagreement": None}
    assert transition_choice(run="current", pack=frozenset(), python=frozenset(), universe=UNIVERSE) == {
        "run": "current", "use": [], "source": "agreed", "disagreement": None,
    }

    differs = transition_choice(run="current", pack=frozenset({"alpha", "gamma"}),
                                python=frozenset({"alpha", "beta", "viewer"}), universe=UNIVERSE)
    assert differs == {
        "run": "current", "use": ["alpha", "beta", "viewer"], "source": "python",
        "disagreement": {"run": "current", "only_pack": ["gamma"], "only_python": ["beta", "viewer"]},
    }, f"A disagreement must keep the Python result and record both sides: {differs}"
    # The Python result is used even when the pack selects more.
    assert transition_choice(run="current", pack=UNIVERSE, python=frozenset(), universe=UNIVERSE)["use"] == []

    unverified = transition_choice(run="current", pack=None, python=frozenset({"alpha"}), universe=UNIVERSE)
    assert unverified == {"run": "current", "use": sorted(UNIVERSE), "source": "full", "disagreement": None}

    for pack, python in ((frozenset({"delta"}), frozenset()), (frozenset(), frozenset({"delta"}))):
        with pytest.raises(ValueError):
            transition_choice(run="current", pack=pack, python=python, universe=UNIVERSE)
