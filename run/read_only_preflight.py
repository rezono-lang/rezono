"""Compare an expected offer with injected price and stock observations."""

from collections.abc import Callable
from contextlib import closing
from functools import cache
from pathlib import Path
from typing import TypedDict

from rezono_compiler import batch, facts, pack, rules, scenarios

_PACK_DIR = Path(__file__).resolve().parent / "packs" / "offer-selection"


class OfferInspection(TypedDict):
    sku: str
    expected_price: int
    observed_price: int | None
    required_stock: int
    observed_stock: int | None
    findings: list[str]


@cache
def _offer_selection() -> tuple[pack.Pack, rules.Program]:
    model = pack.read(_PACK_DIR)
    program = rules.load(model.rules)
    return model, program


def _read(reader: Callable[[str], int | None], sku: str) -> int | None:
    try:
        return reader(sku)
    except OSError:
        return None


def _derive_findings(
    sku: str,
    expected_price: int,
    required_stock: int,
    observed_price: int | None,
    observed_stock: int | None,
) -> list[str]:
    model, program = _offer_selection()
    record: dict[str, object] = {
        "id": sku,
        "expected_price": expected_price,
        "required_stock": required_stock,
    }
    if observed_price is not None:
        record["observed_price"] = observed_price
    if observed_stock is not None:
        record["observed_stock"] = observed_stock
    runtime_rows = facts.rows_of(model, {"preflight_offer": [record]})
    inputs = scenarios.rule_rows(model, program, runtime_rows)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        derived = batch.read(connection, program, ["preflight_finding", "preflight_finding_rank"])
    expected = {finding for row_sku, finding in derived["preflight_finding"] if row_sku == sku}
    ranked = sorted(
        (int(rank), finding)
        for row_sku, rank, finding in derived["preflight_finding_rank"]
        if row_sku == sku and finding in expected
    )
    if {finding for _, finding in ranked} != expected:
        raise ValueError("incomplete finding rank for preflight findings")
    return [finding for _, finding in ranked]


def inspect_offer(
    sku: str,
    expected_price: int,
    required_stock: int,
    read_price: Callable[[str], int | None],
    read_stock: Callable[[str], int | None],
) -> OfferInspection:
    """Read each observation once and report price drift and stock independently."""
    if not isinstance(sku, str) or not sku:
        raise ValueError("SKU must be a nonempty string")
    for label, value in (("expected price", expected_price), ("required stock", required_stock)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{label} must be a nonnegative integer")

    observed_price = _read(read_price, sku)
    observed_stock = _read(read_stock, sku)
    for label, value in (("observed price", observed_price), ("observed stock", observed_stock)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{label} must be a nonnegative integer or unknown")

    findings = _derive_findings(sku, expected_price, required_stock, observed_price, observed_stock)
    return {
        "sku": sku,
        "expected_price": expected_price,
        "observed_price": observed_price,
        "required_stock": required_stock,
        "observed_stock": observed_stock,
        "findings": findings,
    }
