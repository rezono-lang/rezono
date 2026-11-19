"""NoCloud meta-data naming each node after its machine, from decisions/run-cluster-shape.md."""

import pytest

from offline_cases import implementation


@pytest.mark.xfail(strict=True, reason="Read decisions/run-cluster-shape.md, section Converters, Node names. Implement meta_data in run/nocloud_meta.py.")
def test_nocloud_meta():
    meta_data = implementation("nocloud_meta.py", "meta_data")
    assert meta_data("m-a") == b"instance-id: m-a\nlocal-hostname: m-a\n"
    uuid = "cb676a46-66fd-4dfb-b839-443f2e6c0b60"
    assert meta_data(uuid) == f"instance-id: {uuid}\nlocal-hostname: {uuid}\n".encode()
    assert meta_data("a" * 63) == f"instance-id: {'a' * 63}\nlocal-hostname: {'a' * 63}\n".encode()
    for name in ("", "M-A", "m_a", "-m", "m-", "m.a", "a" * 64, "m a", "m-a\nx"):
        with pytest.raises(ValueError):
            meta_data(name)
