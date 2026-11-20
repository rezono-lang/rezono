"""Supplied safety verdicts can block a step but never authorize one in the ordinary publication."""
import pytest

from rezono_canon import canonical_bytes
from round_visibility_publication import checked_loop_publication


RUN, CUT = "run", "cut-10"


def _batch_records():
    """Claim every visible subset of a width-two batch proved, as an untrusted submitter could."""
    subsets = {"empty": (), "only-a": ("a",), "only-b": ("b",), "both": ("a", "b")}
    visible = {"empty": ("empty",), "only-a": ("empty", "only-a"), "only-b": ("empty", "only-b"),
               "both": ("empty", "only-a", "only-b", "both")}
    return {
        "loop_batch_domain": [{"id": "selection", "width": 2}],
        "loop_batch_candidate": [{"id": name, "domain": "selection", "size": len(steps), "verdict": "proved"}
                                 for name, steps in subsets.items()],
        "loop_batch_step": [{"id": "a", "priority": 1}, {"id": "b", "priority": 2}],
        "loop_batch_member": [{"id": f"{name}-{i}", "batch": name, "step": step, "position": i}
                              for name, steps in subsets.items() for i, step in enumerate(steps)],
        "loop_batch_visible": [{"id": f"{name}-{subset}", "batch": name, "subset": subset}
                               for name, seen in visible.items() for subset in seen],
        "loop_batch_write": [{"id": "write-a", "step": "a", "target": "slot-a"},
                             {"id": "write-b", "step": "b", "target": "slot-b"}],
    }


def test_supplied_verdicts_authorize_nothing(tmp_path):
    records = {
        "loop_active_run": [{"id": RUN}],
        "loop_sweep_receipt": [{"id": CUT, "run": RUN, "event_time": 10}],
        "loop_step": [{"id": step} for step in ("a", "b", "c")],
        "loop_step_safety_check": [
            {"id": "check-a", "run": RUN, "step": "a", "cut": CUT,
             "obligation": "target-readable", "verdict": "proved", "reason": "submitted-positive"},
            {"id": "check-b", "run": RUN, "step": "b", "cut": CUT,
             "obligation": "target-readable", "verdict": "proved", "reason": "submitted-positive"},
            {"id": "check-c", "run": RUN, "step": "c", "cut": CUT,
             "obligation": "target-readable", "verdict": "refuted", "reason": "target-missing"},
        ],
        **_batch_records(),
    }
    retained = {"round-policy": canonical_bytes({"run": RUN, "cut": CUT, "width": 2})}
    _, rows, _ = checked_loop_publication(tmp_path, records, retained=retained)

    # The counterexample: blocking grounds still come from supplied refutations.
    assert (RUN, "c", "target-readable", "target-missing") in rows("waiting")
    authorized = {relation: rows(relation) for relation in
                  ("safe_alone", "loop_certified_batch", "loop_selected_batch")}
    assert authorized == {relation: set() for relation in authorized}, (
        f"Supplied verdicts authorized steps or batches: {authorized}"
    )
    assert not {row[1] for row in rows("ready")} & {"a", "b"}, f"Supplied verdicts made steps ready: {rows('ready')}"
