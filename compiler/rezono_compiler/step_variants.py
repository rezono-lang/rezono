"""Evaluate one speculative round without changing its base facts or observation evidence."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import closing
from datetime import date
from typing import TypeAlias, TypedDict

from . import batch, calc, facts, seal
from .emit import id_type
from .pack import Pack
from .rules import Program

Value: TypeAlias = str | int | bool | date
Row: TypeAlias = tuple[Value, ...]
Rows: TypeAlias = dict[str, list[Row]]
Delta: TypeAlias = tuple[str, Row, int]
TextRow: TypeAlias = tuple[str, ...]


class Variant(TypedDict):
    observations: dict[str, bytes]
    facts: Rows
    base_rows: dict[str, set[TextRow]]
    variant_rows: dict[str, set[TextRow]]
    base_witnesses: dict[str, list[TextRow]]
    variant_witnesses: dict[str, list[TextRow]]


def _tables(model: Pack) -> dict[str, tuple[tuple[str, ...], int]]:
    tables = {}
    for name, kind in model.kinds.items():
        identity = id_type(model, name)
        tables[name] = ((identity,), 1)
        for slot in kind.slots.values():
            # A scalar slot has one value per subject; a set is keyed by the whole member.
            tables[slot.table] = ((identity, slot.type.sql), 2 if slot.multivalued else 1)
    return tables


def _typed_row(relation: str, row: Sequence[Value], types: tuple[str, ...]) -> Row:
    if not isinstance(row, (tuple, list)) or len(row) != len(types):
        raise ValueError(f"{relation}: expected a typed row with {len(types)} columns")
    try:
        return tuple(facts.typed(sql_type, value, f"{relation} column {column}")
                     for column, (sql_type, value) in enumerate(zip(types, row, strict=True), 1))
    except facts.LoadError:
        raise ValueError(f"{relation}: row values do not match the declared column types") from None


def _vary(model: Pack, original: Rows, delta: Iterable[Delta]) -> Rows:
    tables = _tables(model)
    writes: dict[str, dict[Row, dict[int, Row]]] = defaultdict(dict)
    for relation, values, weight in delta:
        if relation not in tables:
            raise ValueError(f"{relation}: a delta must name a modeled fact table")
        if type(weight) is not int or weight not in (-1, 1):
            raise ValueError(f"{relation}: a row weight must be -1 or +1")
        types, key_width = tables[relation]
        row = _typed_row(relation, values, types)
        change = writes[relation].setdefault(row[:key_width], {})
        if weight in change:
            raise ValueError(f"{relation}: competing writes for one row key")
        change[weight] = row

    variant = original.copy()
    for relation, changes in writes.items():
        types, key_width = tables[relation]
        old: dict[Row, list[Row]] = defaultdict(list)
        unchanged = []
        for values in original.get(relation, ()):
            row = _typed_row(relation, values, types)
            key = row[:key_width]
            if key in changes:
                old[key].append(row)
            else:
                unchanged.append(values)
        for key, change in changes.items():
            removed = change.get(-1)
            inserted = change.get(1)
            if removed is not None:
                if old[key] != [removed]:
                    raise ValueError(f"{relation}: the exact old row is absent or ambiguous")
            elif old[key]:
                raise ValueError(f"{relation}: insertion requires a fresh row key")
            if inserted is not None:
                if inserted == removed:
                    raise ValueError(f"{relation}: cancelling writes for one row key")
                unchanged.append(inserted)
        variant[relation] = sorted(unchanged, key=repr)
    return variant


def _evaluate(model: Pack, program: Program, rows: Rows, calculation: calc.Program | None):
    connection, _, _ = batch.run(model, program, rows, calculation)
    with closing(connection):
        return batch.read(connection, program), batch.witnesses(connection, program)


def evaluate_variant(
    model: Pack, program: Program, base: Mapping[str, Sequence[Row]],
    observations: Mapping[str, bytes], delta: Iterable[Delta],
) -> Variant:
    """Apply the entire signed delta against the original keys, then evaluate both states."""
    evidence = dict(observations)
    if any(not isinstance(data, bytes) for data in evidence.values()):
        raise ValueError("observations must be immutable bytes")
    original = {relation: list(rows) for relation, rows in base.items()}
    variant = _vary(model, original, delta)
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    base_rows, base_witnesses = _evaluate(model, program, original, calculation)
    variant_rows, variant_witnesses = _evaluate(model, program, variant | seal.row_sha256(model, variant), calculation)
    return {
        "observations": evidence,
        "facts": variant,
        "base_rows": base_rows,
        "variant_rows": variant_rows,
        "base_witnesses": base_witnesses,
        "variant_witnesses": variant_witnesses,
    }
