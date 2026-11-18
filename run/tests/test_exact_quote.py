from fractions import Fraction

import pytest

from offline_cases import implementation


def test_exact_quote():
    quote = implementation("exact_quote.py", "total_micros")
    def line(count, periods, price, setup=0, currency="USD"):
        return dict(quantity=count, billed_periods=periods, period_price_micros=price,
                    setup_price_micros=setup, currency=currency)
    independent = 2 * (2 * Fraction("0.164") + Fraction("0.479")) * 1_000_000
    assert quote([line(2, 2, 164000), line(1, 2, 479000)], "USD") == independent == 1614000
    assert quote([line(2, 3, 1, 7)], "USD") == 20
    assert quote([], "USD") == 0
    for bad in (line(-1, 2, 1), line(True, 2, 1), line(1, 2, 0.5), line(1, 2, 1, currency="EUR")):
        with pytest.raises(ValueError):
            quote([bad], "USD")
