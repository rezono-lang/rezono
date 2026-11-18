"""Calculate a recorded quote exactly in millionths of its currency."""

from collections.abc import Iterable, Mapping


def _nonnegative_integer(line: Mapping[str, object], field: str) -> int:
    value = line.get(field)
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def total_micros(lines: Iterable[Mapping[str, object]], currency: str) -> int:
    """Sum the billed periods and one setup charge for each requested machine."""
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("a quote requires a currency")

    total = 0
    for line in lines:
        if not isinstance(line, Mapping):
            raise ValueError("each quote line must be a mapping")
        if line.get("currency") != currency:
            raise ValueError("quote line currency must match the quote currency")
        quantity = _nonnegative_integer(line, "quantity")
        periods = _nonnegative_integer(line, "billed_periods")
        price = _nonnegative_integer(line, "period_price_micros")
        setup = _nonnegative_integer(line, "setup_price_micros")
        total += quantity * (periods * price + setup)
    return total
