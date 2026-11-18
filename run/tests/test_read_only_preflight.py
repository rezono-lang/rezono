import pytest

from offline_cases import implementation


def test_read_only_preflight():
    inspect = implementation("read_only_preflight.py", "inspect_offer")
    calls = []
    def reader(kind, value):
        def read(sku):
            calls.append((kind, sku))
            return value
        return read
    sku = "sample"
    result = inspect(sku, 164000, 2, reader("price", 164001), reader("stock", 1))
    assert calls == [("price", sku), ("stock", sku)]
    assert result == {"sku": sku, "expected_price": 164000, "observed_price": 164001,
                      "required_stock": 2, "observed_stock": 1,
                      "findings": ["price_changed", "insufficient_stock"]}
    def unavailable(_):
        raise TimeoutError("no observation")
    result = inspect(sku, 164000, 2, unavailable, reader("stock", 2))
    assert result["observed_price"] is None and result["findings"] == ["price_unknown"]
    assert inspect(sku, 164000, 2, reader("price", 164000), reader("stock", 2))["findings"] == []
