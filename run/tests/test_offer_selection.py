import pytest

from offline_cases import relation


@pytest.mark.xfail(strict=True, reason="Read decisions/run-offline-acceptance.md. Implement run/packs/offer-selection.")
def test_offer_selection():
    options = {
        "small": (164000, 20, 2, 1, "observed", "ignition", "USD"),
        "tie": (164000, 30, 2, 1, "observed", "ignition", "USD"),
        "expensive": (479000, 40, 3, 1, "observed", "ignition", "USD"),
        "no_stock": (1, 5, 1, 1, "observed", "ignition", "USD"),
        "used_disk": (1, 6, 3, 0, "observed", "ignition", "USD"),
        "unknown_cpu": (1, 7, 3, 1, "unknown", "ignition", "USD"),
        "boot": (1, 8, 3, 1, "observed", "other", "USD"),
        "currency": (1, 9, 3, 1, "observed", "ignition", "EUR"),
    }
    columns = ("price_micros", "tie_rank", "stock", "free_disks", "virtualization", "boot", "currency")
    facts = {"offer": [(key,) for key in options], "demand": [("two",), ("four",)],
             "demand__quantity": [("two", 2), ("four", 4)],
             "demand__currency": [("two", "USD"), ("four", "USD")],
             "demand__boot": [("two", "ignition"), ("four", "ignition")]}
    for index, name in enumerate(columns):
        facts["offer__" + name] = [(key, row[index]) for key, row in options.items()]
    assert relation("offer-selection", facts, "selected") == {("two", "small")}
