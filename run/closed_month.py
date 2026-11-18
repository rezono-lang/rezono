"""Replay a billing close against the exact price publication it names."""

from collections.abc import Iterable
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json
import re
from typing import Literal, Protocol, TypedDict


class PublicationReader(Protocol):
    def get(self, key: str) -> bytes | None: ...


class PublicationWriter(Protocol):
    def put_new(self, key: str, data: bytes) -> None: ...


class CloseDecision(TypedDict):
    id: str
    month: str
    closed_at: str
    publication_sha256: str


class Receipt(TypedDict):
    id: str
    plan_hash: str
    item: str
    received_at: str


class PeriodReceipt(Receipt):
    kind: Literal["period"]
    start: str
    stop: str


class SetupReceipt(Receipt):
    kind: Literal["once"]
    event_at: str


Observation = PeriodReceipt | SetupReceipt


class CloseReport(TypedDict):
    publication_sha256: str
    total_eur: list[int]
    lines: dict[str, list[int]]
    late: list[tuple[str, str, Literal["arrived_after_cutoff"]]]


def retain(store: PublicationWriter, body: bytes) -> str:
    """Write the edition under its immutable digest and return the digest."""
    digest = sha256(body).hexdigest()
    store.put_new(digest, body)
    return digest


def _rates(store: PublicationReader, digest: str) -> dict[str, Fraction]:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid price publication digest")
    body = store.get(digest)
    if body is None or sha256(body).hexdigest() != digest:
        raise ValueError("price publication unavailable or digest mismatch")

    publication = json.loads(body)
    if not isinstance(publication, dict) or publication.get("currency") != "EUR":
        raise ValueError("the price publication must be in EUR")
    raw_rates = publication.get("rates")
    if not isinstance(raw_rates, dict):
        raise ValueError("the price publication must have line rates")

    rates = {}
    for item, pair in raw_rates.items():
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(value) is not int for value in pair) or pair[1] == 0):
            raise ValueError(f"invalid rational price for {item}")
        rates[item] = Fraction(*pair)
    return rates


def _utc(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise ValueError("billing instants require a UTC offset")
    return instant.astimezone(timezone.utc)


def _month_window(month: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("the close month must have the format YYYY-MM")
    year, number = map(int, month.split("-"))
    start = datetime(year, number, 1, tzinfo=timezone.utc)
    if number == 12:
        return start, datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return start, start.replace(month=number + 1)


def _allocation(observation: Observation, month_start: datetime, month_end: datetime) -> Fraction:
    if observation["kind"] == "once":
        return Fraction(month_start <= _utc(observation["event_at"]) < month_end)
    if observation["kind"] != "period":
        raise ValueError("unknown billing observation kind")

    begin, end = _utc(observation["start"]), _utc(observation["stop"])
    if end <= begin:
        raise ValueError("a billing period must end after it starts")
    overlap = min(end, month_end) - max(begin, month_start)
    quantum = datetime.resolution
    return Fraction(max(0, overlap // quantum), (end - begin) // quantum)


def _ratio(amount: Fraction) -> list[int]:
    return [amount.numerator, amount.denominator]


def report(store: PublicationReader, decision: CloseDecision, observations: Iterable[Observation]) -> CloseReport:
    """Allocate recorded charges by UTC service time, using only pre-close receipts."""
    digest = decision["publication_sha256"]
    rates = _rates(store, digest)
    month_start, month_end = _month_window(decision["month"])
    cutoff = _utc(decision["closed_at"])

    by_id: dict[str, Observation] = {}
    for observation in observations:
        existing = by_id.setdefault(observation["id"], observation)
        if existing != observation:
            raise ValueError(f"conflicting billing observations for {observation['id']}")

    total = Fraction()
    lines = {}
    late: list[tuple[str, str, Literal["arrived_after_cutoff"]]] = []
    for identity, observation in sorted(by_id.items()):
        part = _allocation(observation, month_start, month_end)
        if not part:
            continue
        if _utc(observation["received_at"]) >= cutoff:
            late.append((identity, decision["id"], "arrived_after_cutoff"))
            continue
        item = observation["item"]
        if item not in rates:
            raise ValueError(f"price publication has no rate for {item}")
        amount = rates[item] * part
        lines[identity] = _ratio(amount)
        total += amount

    return {"publication_sha256": digest, "total_eur": _ratio(total), "lines": lines, "late": late}
