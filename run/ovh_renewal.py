"""Check whether an OVHcloud service's renewal and commitment bound the run, per decisions/run-price-enforcement.md."""

from collections.abc import Mapping
from datetime import date, datetime, time, timezone
import re

_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_RENEW_BLOCKS: tuple[tuple[str, bool, str], ...] = (
    ("automatic", True, "renews_automatically"),
    ("forced", True, "renewal_forced"),
    ("deleteAtExpiration", False, "not_deleted_at_expiration"),
)


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


def _check_renew(service: Mapping[str, object], codes: set[str]) -> None:
    renew = service.get("renew")
    if not isinstance(renew, Mapping):
        codes.add("renewal_unknown")
        return
    for field, blocked_when, code in _RENEW_BLOCKS:
        value = renew.get(field)
        if type(value) is not bool:
            codes.add("renewal_unknown")
        elif value is blocked_when:
            codes.add(code)


def blocks(service: Mapping[str, object], deadline: str) -> list[str]:
    """Return sorted blocking codes for an OVHcloud serviceInfo record against a UTC cleanup deadline."""
    if not isinstance(service, Mapping):
        raise ValueError("service must be a mapping")
    deadline_utc = _utc_timestamp(deadline, "deadline")

    codes: set[str] = set()
    _check_renew(service, codes)

    expiration_date = _parse_day(service.get("expiration"))
    if expiration_date is None:
        codes.add("expiration_unknown")
    else:
        expiration_utc = datetime.combine(expiration_date, time.min, timezone.utc)
        if expiration_utc <= deadline_utc:
            codes.add("period_ends_before_deadline")

    if "engagedUpTo" not in service:
        codes.add("engagement_unknown")
    else:
        engaged_raw = service["engagedUpTo"]
        if engaged_raw is not None:
            engaged_date = _parse_day(engaged_raw)
            if engaged_date is None:
                codes.add("engagement_unknown")
            elif expiration_date is not None and engaged_date > expiration_date:
                codes.add("engaged_beyond_expiration")

    return sorted(codes)
