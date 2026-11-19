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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/loop-certificate-admission.md sections 1 and 2 and decisions/admission-transport.md "
        "section 8. A supplied proved verdict in loop_step_safety_check or loop_batch_candidate is a claim: it "
        "must not derive safe_alone, loop_certified_batch, loop_selected_batch or ready, while a supplied "
        "refutation still yields its waiting row. Keep only the derivations from the protected inputs "
        "verified_round and verified_round_member, and keep loop/tests/test_batch_visible_prefixes.py green by "
        "moving the verdict-based selection into the speculative evaluation of loop/batch_selection.py under "
        "internal names. Write in packs/std-loop and loop/batch_selection.py. Waits for "
        "test_verified_round_authorizes_steps and test_ready_requires_checked_batch_member (same std-loop "
        "files; ready takes its certified meaning there)."
    ),
)
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
