"""Synthetic records admitted by the packaged schema, independent of the rule implementation."""

from pathlib import Path

PACKS = Path(__file__).resolve().parents[2] / "packs"
LOOP = PACKS / "std-loop"
ORDER = PACKS / "std-order"


def records(link=True):
    return {
        "loop_step": [{"id": "seed", "precedes": ["build"]},
                      {"id": "build", "precedes": ["ship"] if link else []}, {"id": "ship"}],
        "loop_active_run": [{"id": "current"}],
        "loop_completion": [
            {"id": "def-a", "run": "current", "step": "seed", "token": "seeded", "reason": "source-a"},
            {"id": "def-b", "run": "current", "step": "build", "token": "built", "reason": "source-b"},
            {"id": "def-old", "run": "prior", "step": "seed", "token": "previous", "reason": "old-def"},
        ],
        "loop_expectation": [{"id": "seeded", "value": "yes"}, {"id": "built", "value": "yes"}],
        "loop_observation": [
            {"id": "event-old", "run": "prior", "token": "seeded", "event_time": 20, "state": "known",
             "value": "yes", "reason": "old-evidence"},
            {"id": "event-now", "run": "current", "token": "built", "event_time": 3, "state": "known",
             "value": "yes", "reason": "current-evidence"},
        ],
    }


def evaluate(model, data, verified=None):
    """`verified` gives the rows that admission fills into the protected relations, such as
    verified_receipt and verified_member (decisions/admission-transport.md section 5). A program
    that does not declare a relation leaves its rows out."""
    from rezono_compiler import batch, explain, facts, rules, scenarios

    program = rules.load(model.rules)
    admitted = facts.rows_of(model, data)
    inputs = {**scenarios.rule_rows(model, program, admitted), **(verified or {})}
    with batch.connect(program, inputs) as con:
        batch.compute(con, program)
        rows = batch.read(con, program, [*program.base_used(), *program.derived()])
        explainer = explain.Explainer(program, rows, batch.witnesses(con, program))
    return program, rows, explainer
