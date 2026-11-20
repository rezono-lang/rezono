"""Read one plan's terms from a captured public OVHcloud catalog, per decisions/run-price-enforcement.md."""

from collections.abc import Mapping
from fractions import Fraction
from hashlib import sha256
import json

_UCENTS_PER_UNIT = 10**8


def _reject_constant(token: str) -> object:
    raise ValueError(f"invalid JSON constant: {token}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate catalog JSON key: {key!r}")
        result[key] = value
    return result


def _parse_catalog(catalog: bytes) -> Mapping[str, object]:
    if not isinstance(catalog, bytes):
        raise ValueError("catalog must be bytes")
    try:
        document = json.loads(
            catalog.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("catalog is not valid UTF-8 JSON") from exc
    if not isinstance(document, Mapping):
        raise ValueError("catalog must be a JSON object")
    return document


def _nonempty_str(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _fraction(pricing: Mapping[str, object], field: str) -> list[int]:
    value = pricing.get(field)
    if type(value) is not int or value < 0:
        raise ValueError(f"pricing {field} must be a nonnegative integer")
    amount = Fraction(value, _UCENTS_PER_UNIT)
    return [amount.numerator, amount.denominator]


def _select_candidates(pricings: list[object], mode: str) -> tuple[Mapping[str, object], Mapping[str, object]]:
    installations: list[Mapping[str, object]] = []
    renews: list[Mapping[str, object]] = []
    for pricing in pricings:
        if not isinstance(pricing, Mapping):
            raise ValueError("each pricing must be an object")
        if type(pricing.get("commitment")) is not int or pricing["commitment"] != 0:
            continue
        if pricing.get("mode") != mode:
            continue
        capacities = pricing.get("capacities")
        if not isinstance(capacities, list) or not all(isinstance(item, str) for item in capacities):
            raise ValueError("pricing capacities must be a list of strings")
        has_installation = "installation" in capacities
        has_renew = "renew" in capacities
        if has_installation and has_renew:
            raise ValueError("pricing cannot combine installation and renew capacities")
        if has_installation:
            installations.append(pricing)
        if (
            has_renew
            and type(pricing.get("interval")) is int
            and pricing["interval"] == 1
            and pricing.get("intervalUnit") == "month"
        ):
            renews.append(pricing)

    if len(installations) != 1 or len(renews) != 1:
        raise ValueError("plan requires exactly one installation and one monthly renew candidate")
    installation, renew = installations[0], renews[0]
    for candidate in (installation, renew):
        kind = _nonempty_str(candidate, "type")
        if kind == "consumption":
            raise ValueError("consumption pricing cannot guarantee a fixed bound")
    return installation, renew


def terms(catalog: bytes, plan_code: str, mode: str) -> dict[str, object]:
    """Extract fixed setup and monthly renewal terms for one plan from a catalog response."""
    if not isinstance(plan_code, str) or not plan_code.strip():
        raise ValueError("plan_code must be a nonempty string")
    if not isinstance(mode, str) or not mode.strip():
        raise ValueError("mode must be a nonempty string")

    document = _parse_catalog(catalog)
    locale = document.get("locale")
    if not isinstance(locale, Mapping):
        raise ValueError("catalog requires a locale object")
    currency = _nonempty_str(locale, "currencyCode")

    plans = document.get("plans")
    if not isinstance(plans, list):
        raise ValueError("catalog requires a plans list")
    matching = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            raise ValueError("each plan must be an object")
        if plan.get("planCode") == plan_code:
            matching.append(plan)
    if len(matching) != 1:
        raise ValueError(f"expected one plan for {plan_code!r}, found {len(matching)}")

    plan, = matching
    if _nonempty_str(plan, "pricingType") == "consumption":
        raise ValueError("consumption plan cannot guarantee a fixed bound")
    pricings = plan.get("pricings")
    if not isinstance(pricings, list):
        raise ValueError("plan requires a pricings list")

    installation, renew = _select_candidates(pricings, mode)
    return {
        "currency": currency,
        "setup": _fraction(installation, "price"),
        "setup_tax": _fraction(installation, "tax"),
        "period": _fraction(renew, "price"),
        "period_tax": _fraction(renew, "tax"),
        "interval_months": renew["interval"],
        "source_sha256": sha256(catalog).hexdigest(),
    }
