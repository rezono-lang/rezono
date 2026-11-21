"""Check whether an OVHcloud service's renewal and commitment bound the run, per decisions/run-price-enforcement.md."""

from collections.abc import Mapping
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from functools import cache
from pathlib import Path
import re

from rezono_compiler import batch, facts, pack, rules, scenarios

_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)
_PACK_DIR = Path(__file__).resolve().parent / "packs" / "provider-terms"


@cache
def _provider_terms() -> tuple[pack.Pack, rules.Program, dict[str, list[tuple]]]:
    model = pack.read(_PACK_DIR)
    program = rules.load(model.rules)
    states = scenarios.fact_states(model, _PACK_DIR, diagnostics=False)
    if not states:
        raise ValueError("provider-terms pack must provide fact states")
    return model, program, states[0][3]


def _utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 timestamp string")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if instant.utcoffset() is None:
        raise ValueError(f"{label} requires a UTC offset")
    return instant.astimezone(timezone.utc)


def _parse_day(value: object) -> date | None:
    if not isinstance(value, str) or _DAY_RE.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_microseconds(instant: datetime) -> int:
    return (instant - _EPOCH) // _MICROSECOND


def _day_microseconds(day: date) -> int:
    return _to_microseconds(datetime.combine(day, time.min, timezone.utc))


def _service_facts(service: Mapping[str, object], deadline_utc: datetime) -> dict[str, list[dict[str, object]]]:
    service_row: dict[str, object] = {
        "id": "service",
        "deadline_us": _to_microseconds(deadline_utc),
    }
    expiration_date = _parse_day(service.get("expiration"))
    if expiration_date is not None:
        service_row["expiration_us"] = _day_microseconds(expiration_date)

    engaged_known = False
    if "engagedUpTo" in service:
        engaged_raw = service["engagedUpTo"]
        if engaged_raw is None:
            engaged_known = True
        else:
            engaged_date = _parse_day(engaged_raw)
            if engaged_date is not None:
                engaged_known = True
                service_row["engaged_up_to_us"] = _day_microseconds(engaged_date)
    service_row["engaged_known"] = engaged_known

    renew_rows: list[dict[str, object]] = []
    renew = service.get("renew")
    if isinstance(renew, Mapping):
        for field, value in renew.items():
            if isinstance(field, str) and field.strip() and type(value) is bool:
                renew_rows.append({
                    "id": f"service/{field}",
                    "service": "service",
                    "field": field,
                    "value": value,
                })

    return {
        "service": [service_row],
        "service_renew_flag": renew_rows,
    }


def blocks(service: Mapping[str, object], deadline: str) -> list[str]:
    """Return sorted blocking codes for an OVHcloud serviceInfo record against a UTC cleanup deadline."""
    if not isinstance(service, Mapping):
        raise ValueError("service must be a mapping")
    deadline_utc = _utc_timestamp(deadline, "deadline")

    model, program, pack_facts = _provider_terms()
    runtime_rows = facts.rows_of(model, _service_facts(service, deadline_utc))
    merged = {
        table: [*pack_facts.get(table, ()), *runtime_rows.get(table, ())]
        for table in pack_facts.keys() | runtime_rows.keys()
    }
    inputs = scenarios.rule_rows(model, program, merged)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        derived = batch.read(connection, program, ["renewal_block"])["renewal_block"]
    return sorted(code for _, code in derived)
