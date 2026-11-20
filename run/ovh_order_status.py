"""Read a recorded OVHcloud order status via the provider-terms pack, per decisions/run-price-enforcement.md."""

from contextlib import closing
from functools import cache
import json
from pathlib import Path

from rezono_compiler import batch, facts, pack, rules, scenarios

_PACK_DIR = Path(__file__).resolve().parent / "packs" / "provider-terms"


@cache
def _provider_terms() -> tuple[pack.Pack, rules.Program, dict[str, list[tuple]]]:
    model = pack.read(_PACK_DIR)
    program = rules.load(model.rules)
    states = scenarios.fact_states(model, _PACK_DIR, diagnostics=False)
    pack_facts = states[0][3] if states else {}
    return model, program, pack_facts


def outcome(body: bytes) -> str:
    """Read the raw status body; anything other than one JSON string is unresolved without a lookup."""
    try:
        status = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return "unresolved"
    if not isinstance(status, str):
        return "unresolved"

    model, program, pack_facts = _provider_terms()
    runtime_rows = facts.rows_of(model, {
        "order": [{"id": "order", "status": status}],
    })
    merged = {
        table: [*pack_facts.get(table, ()), *runtime_rows.get(table, ())]
        for table in pack_facts.keys() | runtime_rows.keys()
    }
    inputs = scenarios.rule_rows(model, program, merged)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        outcomes = batch.read(connection, program, ["order_outcome"])["order_outcome"]
    if len(outcomes) != 1:
        raise ValueError("provider terms derived unexpected order_outcome rows")
    (_, derived_outcome), = outcomes
    return derived_outcome
