from hashlib import sha256

import pytest

from offline_cases import implementation, FIXTURE, SOURCE


@pytest.mark.xfail(strict=True, reason="Read decisions/run-offline-acceptance.md. Implement run/price_capture.py.")
def test_price_capture():
    read = implementation("price_capture.py", "hourly_micros")
    raw = (FIXTURE / "public-price-response.json").read_bytes()
    assert read(raw, SOURCE) == {"vbm-4c-32gb": 164000, "vbm-8c-132gb": 479000}
    with pytest.raises(ValueError):
        read(raw + b" ", SOURCE)
    tiny = b'{"plans_metal":[{"id":"x","hourly_cost":0.000001}]}'
    assert read(tiny, sha256(tiny).hexdigest()) == {"x": 1}
    too_precise = tiny.replace(b"0.000001", b"0.0000001")
    with pytest.raises(ValueError):
        read(too_precise, sha256(too_precise).hexdigest())
