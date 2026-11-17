"""Part (b) of admission: the step around the validation of rows (ruling 2 of 11-11-2026).

A batch of facts enters only with a source, and the same delivery is admitted once. The rows themselves are
judged by part (a) (rows.py; later Reckon Data's L0 reader behind the same interface). A batch with records of a
control kind (`plane: control`, DV1) enters only from a reviewed proposal: decided values change by review, never
by a direct delta (O13). Each of their records names its decision; part (a) holds that, so the batch path holds it
too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rows import Refusal, rows
from .schema import Schema


@dataclass(frozen=True)
class Admitted:
    """What one batch gave: its rows per table (empty when anything was refused), every refusal, and whether
    the batch was a second delivery of one already admitted (then it adds nothing)."""

    rows: dict[str, list[tuple]] = field(default_factory=dict)
    refusals: tuple[Refusal, ...] = ()
    duplicate: bool = False

    @property
    def admitted(self) -> bool:
        return not self.refusals and not self.duplicate


class Admission:
    """Admission for one schema. `seen` holds the keys of the deliveries admitted so far: the caller's input log
    keeps them, so a restart that reads the log back admits nothing twice."""

    def __init__(self, schema: Schema, seen=()):
        self.schema = schema
        self.seen = set(seen)

    def admit(self, data, *, source: str, event: str | None = None, reviewed: str | None = None) -> Admitted:
        """A batch of records per kind from `source`. `event` is the delivery's own key (an event id, a position
        in the source); without one the batch is its own key, by its rows. `reviewed` names the reviewed proposal
        the batch comes from (for a pack's own facts: the commit of the reviewed pack); without one a batch with a
        record of a control kind is refused. A batch is all or nothing: one refusal and no row of it is admitted."""
        if not source:
            return Admitted(refusals=(Refusal("source_missing", "", self.schema.sha256),))
        found, refusals = rows(self.schema, data)
        if refusals:
            return Admitted(refusals=tuple(refusals))
        if not reviewed:
            control = [t for t in found if t in self.schema.kinds and self.schema.control(t)]
            if control:
                return Admitted(refusals=tuple(Refusal("control_unreviewed", t, self.schema.sha256)
                                               for t in control))
        key = (source, event if event is not None else repr(sorted(found.items())))
        if key in self.seen:
            return Admitted(duplicate=True)
        self.seen.add(key)
        return Admitted(rows=found)
