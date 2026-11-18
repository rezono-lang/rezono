import pytest

from offline_cases import implementation, case


def test_installation_input():
    machines = implementation("installation_input.py", "machines")
    observed = case()["machine_observations"]
    expected = [(m["id"], m["address"], m["boot_disk"], m["data_disk"]) for m in observed]
    assert machines(list(reversed(observed))) == expected
    for records in ([observed[0], observed[0]], [dict(observed[0], data_disk="boot-1")],
                    [observed[0], dict(observed[1], data_disk="data-1")],
                    [dict(observed[0], address="")]):
        with pytest.raises(ValueError):
            machines(records)
