import pytest

from budget import minutes, verdict


@pytest.mark.parametrize("value", [True, 0, -1, 0.5, "1"])
def test_budget_requires_positive_whole_minutes(value):
    with pytest.raises(ValueError, match="whole number of minutes"):
        minutes({"publish": {"budget_minutes": value}})


def test_elapsed_time_equal_to_budget_is_allowed():
    budget = minutes({"publish": {"budget_minutes": 2}})
    assert budget == 2
    over, _ = verdict(budget, 120, [])
    assert not over


def test_overrun_reports_slowest_pack_and_its_largest_phase():
    lines = [
        "time blue read 3s",
        "time blue write 8s",
        "time green write 10s",
        "time green total 10s",
    ]
    over, report = verdict(2, 121, lines)
    assert over
    assert "over it by 0 min 1 s" in report
    assert "slowest pack is blue (11 s)" in report
    assert "largest phase write (8 s)" in report
