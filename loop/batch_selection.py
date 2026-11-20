"""Select a width-bounded batch from independently supplied visible-state verdicts."""

from collections.abc import Iterator, Mapping, Set
from functools import cache
from itertools import combinations
from pathlib import Path
from typing import TypedDict

from rezono_compiler import batch, facts, pack, rules, rules_dl, scenarios


Members = frozenset[str]

# Speculative selection lives only in this certifier evaluation under internal names; ordinary
# publication authorizes batches only through admitted verified rounds.
_SPECULATIVE_RULES = """\
.decl speculative_batch_unproved(batch: symbol)
speculative_batch_unproved(b) :-
    loop_batch_visible__batch(row, b), loop_batch_visible__subset(row, v),
    !loop_batch_candidate__verdict(v, "proved").

.decl speculative_batch_write_conflict(batch: symbol)
speculative_batch_write_conflict(b) :-
    loop_batch_member__batch(x, b), loop_batch_member__batch(y, b),
    loop_batch_member__position(x, i), loop_batch_member__position(y, j), i < j,
    loop_batch_member__step(x, s), loop_batch_member__step(y, t),
    loop_batch_write__step(a, s), loop_batch_write__step(z, t),
    loop_batch_write__target(a, slot), loop_batch_write__target(z, slot).

.decl speculative_certified_batch(batch: symbol, domain: symbol, size: number)
speculative_certified_batch(b, d, n) :-
    loop_batch_candidate__domain(b, d), loop_batch_candidate__size(b, n),
    loop_batch_domain__width(d, w), n > 0, n <= w,
    loop_batch_visible__batch(full, b), loop_batch_visible__subset(full, b),
    loop_batch_visible__batch(base, b), loop_batch_visible__subset(base, e),
    loop_batch_candidate__domain(e, d), loop_batch_candidate__size(e, 0),
    !speculative_batch_unproved(b), !speculative_batch_write_conflict(b).

.decl speculative_batch_priority(batch: symbol, position: number, priority: number)
speculative_batch_priority(b, i, p) :-
    loop_batch_member__batch(m, b), loop_batch_member__position(m, i),
    loop_batch_member__step(m, s), loop_batch_step__priority(s, p).

.decl speculative_batch_difference(first: symbol, second: symbol, position: number)
speculative_batch_difference(a, b, i) :-
    speculative_certified_batch(a, d, n), speculative_certified_batch(b, d, n),
    speculative_batch_priority(a, i, p), speculative_batch_priority(b, i, q), p != q.

.decl speculative_batch_earlier_difference(first: symbol, second: symbol, position: number)
speculative_batch_earlier_difference(a, b, i) :-
    speculative_batch_difference(a, b, i), speculative_batch_difference(a, b, j), j < i.

.decl speculative_batch_preceded(batch: symbol)
speculative_batch_preceded(b) :-
    speculative_certified_batch(a, d, m), speculative_certified_batch(b, d, n), m > n.
speculative_batch_preceded(b) :-
    speculative_batch_difference(a, b, i), !speculative_batch_earlier_difference(a, b, i),
    speculative_batch_priority(a, i, p), speculative_batch_priority(b, i, q), p < q.

.decl speculative_selected_batch(batch: symbol)
speculative_selected_batch(b) :- speculative_certified_batch(b, _, _), !speculative_batch_preceded(b).
"""


class BatchSelection(TypedDict):
    certified: tuple[Members, ...]
    selected: Members


@cache
def _theory() -> tuple[pack.Pack, rules.Program]:
    path = Path(__file__).resolve().parents[1] / "packs" / "std-loop"
    model = pack.read(path)
    inputs = {
        name: cols
        for name, cols in rules_dl.base_tables(model).items()
        if name.startswith("loop_batch_") and all(t for _, t in cols)
    }
    program = rules_dl.read_program(
        _SPECULATIVE_RULES, "loop/batch_selection.py", inputs, "speculative_batch_selection",
    )
    return model, rules.load(program)


def _subsets(steps: tuple[str, ...], width: int) -> Iterator[tuple[str, ...]]:
    for size in range(min(width, len(steps)) + 1):
        yield from combinations(steps, size)


def select_batch(
    priorities: Mapping[str, int],
    verdicts: Mapping[Members, bool | None],
    *,
    effects: Mapping[str, Mapping[str, Set[str]]],
    width: int,
) -> BatchSelection:
    """Return the certified domain and chosen steps; missing or unknown verdicts prove no subset safe."""
    low, high = pack.BIGINT
    if type(width) is not int or not 1 <= width <= high:
        raise ValueError("batch width must be a positive whole number in the engine range")
    if effects.keys() - priorities.keys() or any(
        len(prefix) <= width and not prefix <= priorities.keys() for prefix in verdicts
    ):
        raise ValueError("every step in the batch domain needs a priority")
    if any(type(priority) is not int or not low <= priority <= high for priority in priorities.values()):
        raise ValueError("every step needs a whole-number priority in the engine range")
    if len(set(priorities.values())) != len(priorities):
        raise ValueError("batch priorities must be distinct")
    ordered = tuple(sorted(priorities, key=priorities.__getitem__))
    steps, write_rows = [], []
    for step in ordered:
        writes = effects.get(step, {}).get("write")
        if not isinstance(writes, Set) or any(not isinstance(target, str) or not target for target in writes):
            raise ValueError(f"step {step!r} needs a set of write targets")
        steps.append({"id": step, "priority": priorities[step]})
        for target in sorted(writes):
            write_rows.append({"id": f"write-{len(write_rows)}", "step": step, "target": target})

    domain = {f"batch-{i}": members for i, members in enumerate(_subsets(ordered, width))}
    identity = {frozenset(members): name for name, members in domain.items()}
    candidates, members, visible_rows = [], [], []
    for name, steps_in_batch in domain.items():
        candidate = {"id": name, "domain": "selection", "size": len(steps_in_batch)}
        key = frozenset(steps_in_batch)
        if key in verdicts:
            verdict = verdicts[key]
            if verdict is not None and type(verdict) is not bool:
                raise ValueError("a visible subset verdict must be boolean or unknown")
            candidate["verdict"] = "unknown" if verdict is None else "proved" if verdict else "refuted"
        candidates.append(candidate)
        members.extend({"id": f"{name}-{i}", "batch": name, "step": step, "position": i}
                       for i, step in enumerate(steps_in_batch))
        for i, prefix in enumerate(_subsets(steps_in_batch, len(steps_in_batch))):
            visible_rows.append({"id": f"{name}-{i}", "batch": name, "subset": identity[frozenset(prefix)]})

    model, program = _theory()
    records = {
        "loop_batch_domain": [{"id": "selection", "width": width}],
        "loop_batch_candidate": candidates,
        "loop_batch_step": steps,
        "loop_batch_member": members,
        "loop_batch_visible": visible_rows,
        "loop_batch_write": write_rows,
    }
    inputs = scenarios.rule_rows(model, program, facts.rows_of(model, records))
    outputs = ("speculative_certified_batch", "speculative_selected_batch")
    with batch.connect(program, inputs, threads=1) as connection:
        batch.compute(connection, program)
        rows = batch.read(connection, program, outputs)
    certified = {name for name, _, _ in rows["speculative_certified_batch"]}
    winners = rows["speculative_selected_batch"]
    selected = frozenset()
    if winners:
        (winner,), = winners
        selected = frozenset(domain[winner])
    return {
        "certified": tuple(frozenset(steps) for name, steps in domain.items() if name in certified),
        "selected": selected,
    }
