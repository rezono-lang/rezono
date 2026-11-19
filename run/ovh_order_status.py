"""Map a recorded OVHcloud order status to one run outcome, per decisions/run-price-enforcement.md, Correlation."""

import json
from typing import Literal

Outcome = Literal["not_committed", "pending", "delivered", "refused", "unresolved"]

_OUTCOMES: dict[str, Outcome] = {
    "notPaid": "not_committed",
    "checking": "pending",
    "documentsRequested": "pending",
    "delivering": "pending",
    "delivered": "delivered",
    "cancelled": "refused",
}


def outcome(body: bytes) -> Outcome:
    """Read the raw status body; anything other than one known status string is unresolved."""
    try:
        status = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return "unresolved"
    if not isinstance(status, str):
        return "unresolved"
    return _OUTCOMES.get(status, "unresolved")
