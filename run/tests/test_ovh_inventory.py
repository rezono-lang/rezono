"""Find delivered services still listed by the provider, per decisions/run-price-enforcement.md, Cleanup."""

import pytest

from offline_cases import implementation

DELIVERED = ["srv-2.example.org", "srv-1.example.org"]


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-price-enforcement.md, Cleanup. Implement request() and remaining(listing, delivered) in "
    "run/ovh_inventory.py: an unfiltered account-wide list, compared with the services the plan's orders delivered."
))
def test_ovh_inventory():
    request = implementation("ovh_inventory.py", "request")
    remaining = implementation("ovh_inventory.py", "remaining")

    # A tag filter would make the sweep depend on the tags it is meant to check.
    assert request() == ("GET", "/dedicated/server")
    assert remaining(b'["other.example.org", "srv-1.example.org"]', DELIVERED) == ["srv-1.example.org"]
    assert remaining(b'["srv-2.example.org", "srv-1.example.org"]', DELIVERED) == DELIVERED[::-1]
    assert remaining(b'["other.example.org"]', DELIVERED) == []
    assert remaining(b"[]", DELIVERED) == []
    assert remaining(b'["srv-1.example.org"]', []) == []
    # A listing that is not a complete list of names proves nothing.
    for listing in (b"", b"null", b"{}", b'"srv-1.example.org"', b"[1]", b'["srv-1.example.org", null]',
                    b'["srv-1.example.org", "srv-1.example.org"]', b'["srv-1.example.org"'):
        with pytest.raises(ValueError):
            remaining(listing, DELIVERED)
    with pytest.raises(ValueError):
        remaining(b"[]", ["srv-1.example.org", ""])
