"""Pay one OVHcloud order once through a provider port, per decisions/run-price-enforcement.md, Correlation."""

from collections.abc import Callable
from typing import Literal

ProviderCall = Callable[[str, str, dict[str, object] | None], object]
PayResult = tuple[Literal["submitted", "unresolved"], str]


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def pay(call: ProviderCall, order_id: int, payment_method_id: int) -> PayResult:
    """Submit payment once for one order id; a lost response stays unresolved for status lookup."""
    if not callable(call):
        raise ValueError("call must be callable")
    validated_order = _positive_int(order_id, "order_id")
    validated_method = _positive_int(payment_method_id, "payment_method_id")

    try:
        call(
            "POST",
            f"/me/order/{validated_order}/pay",
            {"paymentMethod": {"id": validated_method}},
        )
    except TimeoutError:
        return "unresolved", str(validated_order)
    return "submitted", str(validated_order)
