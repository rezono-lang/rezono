"""Project delivery status and its witnesses through the packaged loop theory."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal, cast

from rezono_canon import canonical_sha256
from rezono_compiler import batch, explain, facts, modules, pack, rules, scenarios

from loop.typed_recording import instant


StatusState = Literal["pending", "success", "failure"]
Observation = Mapping[str, str]
SCOPE = ("tenant", "delivery", "step", "run")
RELATION = "current_delivery_status"


@dataclass(frozen=True)
class StatusProjection:
    state: StatusState
    reasons: frozenset[str]
    pack_sha256: str
    observations: tuple[dict[str, str | int], ...]
    proofs: tuple[dict, ...]
    latest_at: str = ""


@cache
def _theory() -> tuple[pack.Pack, rules.Program, str]:
    path = Path(__file__).resolve().parents[1] / "packs" / "std-loop"
    model = pack.read(path)
    return model, rules.load(model.rules), modules.pack_hash(path)


def _observations(step: Mapping[str, str], evidence: Iterable[Observation]) -> tuple[dict[str, str | int], ...]:
    scope = {key: step[key] for key in SCOPE}
    records = []
    for row in evidence:
        if not row.get("reason") or not row.get("relation") or any(row.get(key) != value for key, value in scope.items()):
            continue
        at = row.get("at", "")
        record = {**scope, "relation": row["relation"], "reason": row["reason"], "at": at}
        records.append((row.get("id") or canonical_sha256(record), record, instant(at) if at else None))
    ordered_times = {at: index for index, at in enumerate(sorted({at for _, _, at in records if at is not None}))}
    by_id: dict[str, dict[str, str | int]] = {}
    for identity, record, at in records:
        observed = {"id": identity, **record, "event_time": ordered_times[at] if at is not None else -1}
        if by_id.setdefault(identity, observed) != observed:
            raise ValueError(f"conflicting status observations with event ID {identity!r}")
    return tuple(by_id[event] for event in sorted(by_id))


def project_status(step: Mapping[str, str], evidence: Iterable[Observation]) -> StatusProjection:
    """Provide the current state and reproducible, same-scope evidence for publication."""
    observations = _observations(step, evidence)
    model, program, pack_sha256 = _theory()
    if not observations:
        return StatusProjection("pending", frozenset(), pack_sha256, (), ())
    inputs = scenarios.rule_rows(model, program, facts.rows_of(model, {"loop_status_observation": list(observations)}))
    with batch.connect(program, inputs) as connection:
        batch.compute(connection, program)
        rows = batch.read(connection, program, [*program.base_used(), *program.derived()])
        selected = sorted(rows[RELATION])
        if not selected:
            return StatusProjection("pending", frozenset(), pack_sha256, observations, ())
        witnesses = explain.Explainer(program, rows, batch.witnesses(connection, program))
    snapshot = canonical_sha256({"pack_sha256": pack_sha256, "observations": observations})
    proofs = tuple(witnesses.proof(RELATION, row, snapshot) for row in selected)
    (*_, latest), = rows["status_latest"]
    latest_rank = int(latest)
    latest_at = next(cast(str, row["at"]) for row in observations if row["event_time"] == latest_rank)
    return StatusProjection(cast(StatusState, selected[0][-2]), frozenset(row[-1] for row in selected),
                            pack_sha256, observations, proofs, latest_at)


def project_with_reasons(step: Mapping[str, str], evidence: Iterable[Observation]) -> tuple[StatusState, set[str]]:
    projection = project_status(step, evidence)
    return projection.state, set(projection.reasons)


def project(step: Mapping[str, str], evidence: Iterable[Observation]) -> StatusState:
    return project_status(step, evidence).state
