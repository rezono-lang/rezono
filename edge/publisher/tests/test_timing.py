"""Time per phase (rede_publisher.timing): every moment counts toward one phase, a lent phase is taken out of
the one around it, and the report goes to the log and the step summary only."""

import io

import pytest

from rede_publisher import timing


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(timing.time, "monotonic", lambda: now[0])
    timing._spent.clear()
    timing._stack.clear()
    yield now
    timing._spent.clear()
    timing._stack.clear()


def test_phases_add_up_and_a_lent_phase_is_taken_out(clock):
    timing.switch("compile")
    clock[0] = 2.0
    timing.switch("views")
    clock[0] = 3.0
    with timing.phase("checker"):
        clock[0] = 7.0
        with timing.phase("tiles"):
            clock[0] = 8.0
        clock[0] = 9.0
    clock[0] = 10.0
    assert timing.spent() == {"compile": 2.0, "checker": 5.0, "tiles": 1.0, "views": 2.0}


def test_the_report_goes_to_the_log_and_the_summary_then_starts_again(clock, tmp_path):
    timing.switch("batch")
    clock[0] = 3.0
    with timing.phase("checker"):
        clock[0] = 4.0
    log, summary = io.StringIO(), tmp_path / "summary.md"
    assert timing.report("examples/toy", out=log, summary=str(summary)) == {"batch": 3.0, "checker": 1.0}
    assert log.getvalue().splitlines() == [
        "time examples/toy batch 3.000s 75.0%",
        "time examples/toy checker 1.000s 25.0%",
        "time examples/toy total 4.000s",
    ]
    text = summary.read_text()
    assert "### Publication time: examples/toy" in text
    assert "| **batch** | 3.00 | 75.0% |" in text and "| checker | 1.00 | 25.0% |" in text
    assert timing.spent() == {}


def test_without_a_summary_only_the_log(clock, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    timing.switch("upload")
    clock[0] = 1.0
    log = io.StringIO()
    timing.report("p", out=log)
    assert log.getvalue().startswith("time p upload 1.000s 100.0%")


def test_publish_sh_reads_the_same_lines_for_its_budget(clock, monkeypatch, tmp_path):
    # RV-Z11: deploy/profiles/edge/publish.sh names the slowest pack's largest phase from these lines.
    times = tmp_path / "times"
    monkeypatch.setenv("REDE_TIMES_FILE", str(times))
    for pack in ("a", "b"):
        timing.switch("upload")
        clock[0] += 2.0
        log = io.StringIO()
        timing.report(pack, out=log)
    assert times.read_text(encoding="utf-8").splitlines() == [
        "time a upload 2.000s 100.0%", "time a total 2.000s", "time b upload 2.000s 100.0%", "time b total 2.000s"]
    assert log.getvalue() == "time b upload 2.000s 100.0%\ntime b total 2.000s\n"
