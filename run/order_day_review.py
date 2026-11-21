"""Revalue an order day and review an inert request against recorded approval."""

from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from typing import TypedDict

from rezono_compiler import batch, pack, rules

from run.effective_quote import Edition, pack_currencies, quote_at


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class OrderRequest(TypedDict):
    plan_hash: str
    provider: str
    mode: str
    reference: str
    currency: str
    max_total: list[int]
    expires_at: str


class Review(TypedDict):
    reason: str
    candidate_hash: str
    request: OrderRequest | None


def plan(
    day: str, lines: Iterable[Mapping[str, object]], prices: Iterable[Edition],
    rates: Iterable[Edition], provider: str,
) -> bytes:
    """Bind the effective prices, totals and renderable order lines in the plan bytes."""
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("the plan requires a provider")
    order_day = date.fromisoformat(day)
    start = datetime.combine(order_day, time.min, timezone.utc)
    order_lines = list(lines)
    quote = quote_at(start.isoformat(), order_lines, prices, rates)
    if problems := quote["problems"]:
        raise ValueError(f"effective quote unavailable: {', '.join(problems)}")
    _, _, currencies = pack_currencies()
    currency_keys = tuple(currency.lower() for currency in currencies)
    line_fields = ("sku", "currency", "quantity", "billed_periods", "setup_price_micros")
    payload = {
        "order_day": order_day.isoformat(),
        "provider": provider,
        "lines": [{field: line[field] for field in line_fields} for line in order_lines],
        **{field: quote[field] for field in (*currency_keys, "price_source", "fx_source")},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("review requires recorded timestamps")
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() is None:
        raise ValueError("review timestamps require a UTC offset")
    return instant.astimezone(timezone.utc)


def _amount_bound(value: object, total: list[int]) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    n, d = value
    return type(n) is int and type(d) is int and d > 0 and Fraction(n, d) == Fraction(*total)


def _authorized(
    plan_hash: str, quote_hash: str, currency: str, cost_micros: int,
    approval: Mapping[str, str | int], observed: datetime,
) -> bool:
    sources = {
        "plan": {"plan_hash": plan_hash, "currency": currency},
        "quote": {"plan_hash": quote_hash, "currency": currency, "cost_micros": cost_micros},
        "approval": approval,
        "observation": {"event_us": (observed - EPOCH) // datetime.resolution},
    }
    facts: dict[str, list[tuple[str | int, ...]]] = {"candidate": [(plan_hash,)]}
    for kind, fields in sources.items():
        facts[kind] = [(kind,)]
        facts[f"{kind}__candidate"] = [(kind, plan_hash)]
        for field, value in fields.items():
            facts[f"{kind}__{field}"] = [(kind, value)]

    dispatch = Path(__file__).resolve().parent / "packs" / "dispatch"
    program = rules.load(pack.read(dispatch).rules)
    with closing(batch.connect(program, facts)) as connection:
        batch.compute(connection, program)
        return (plan_hash,) in batch.read(connection, program, ["authorized"])["authorized"]


def review(
    approval: Mapping[str, object], instant: str, day: str, lines: Iterable[Mapping[str, object]],
    prices: Iterable[Edition], rates: Iterable[Edition], guarantee: Mapping[str, object],
) -> Review:
    """Review recorded provider terms offline against the approved plan and its total."""
    provider = guarantee.get("provider")
    if not isinstance(provider, str):
        raise ValueError("the guarantee requires a provider")
    raw = plan(day, lines, prices, rates, provider)
    candidate = json.loads(raw)
    plan_hash = sha256(raw).hexdigest()

    def refuse(reason: str) -> Review:
        return {"reason": reason, "candidate_hash": plan_hash, "request": None}

    approval_hash = approval.get("plan_hash")
    if not isinstance(approval_hash, str) or approval_hash != plan_hash:
        return refuse("renew_approval")
    quote_currency, _, currencies = pack_currencies()
    quote_key = quote_currency.lower()
    currency = approval.get("currency")
    decision = approval.get("decision")
    budget_cents = approval.get("budget_cents")
    if (currency not in currencies or decision not in ("approve", "decline")
            or type(budget_cents) is not int or budget_cents < 0):
        return refuse("invalid_approval")

    observed = _utc(instant)
    approval_end = _utc(approval.get("expires_at"))
    start = _utc(candidate["order_day"] + "T00:00:00Z")
    expires = min(approval_end, _utc(guarantee.get("expires_at")), start + timedelta(days=1))
    if observed >= expires:
        return refuse("expired")
    if observed < start:
        return refuse("before_order_day")

    mode, reference = guarantee.get("mode"), guarantee.get("reference")
    if (mode not in ("binding_quote", "reject_above") or guarantee.get("includes_setup") is not True
            or guarantee.get("currency", quote_currency) != quote_currency or not isinstance(reference, str)
            or not reference.strip() or not _amount_bound(guarantee.get(f"total_{quote_key}"), candidate[quote_key])):
        return refuse("unbound_total")

    # A reject-above request supplies its own cap. A binding quote must carry the provider's plan digest.
    quote_hash = guarantee.get("plan_hash", plan_hash if mode == "reject_above" else None)
    if not isinstance(quote_hash, str) or quote_hash != plan_hash:
        return refuse("unbound_plan")

    # Rounding upward preserves an exact comparison with a whole-micros cap.
    cost_micros = ceil(Fraction(*candidate[currency.lower()]) * 1_000_000)
    cap_micros = budget_cents * 10_000
    if cost_micros > pack.BIGINT[1]:
        return refuse("over_cap" if cost_micros > cap_micros else "amount_out_of_range")
    approval_facts = {
        "plan_hash": approval_hash,
        "currency": currency,
        "decision": decision,
        "cap_micros": min(cap_micros, pack.BIGINT[1]),
        "expires_us": (approval_end - EPOCH) // datetime.resolution,
    }
    if not _authorized(plan_hash, quote_hash, currency, cost_micros, approval_facts, observed):
        return refuse("over_cap" if cost_micros > cap_micros else "not_authorized")

    return {"reason": "authorized", "candidate_hash": plan_hash, "request": {
        "plan_hash": plan_hash, "provider": provider, "mode": mode, "reference": reference,
        "currency": quote_currency, "max_total": candidate[quote_key],
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
    }}
