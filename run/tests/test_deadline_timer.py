"""The on-machine cleanup deadline clock, from decisions/run-server-deadline.md."""

import pytest

from offline_cases import implementation


TIMER = """[Unit]
Description=Power off at the run cleanup deadline

[Timer]
OnCalendar={calendar}
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
"""

SERVICE = """[Unit]
Description=Power off at the run cleanup deadline

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl poweroff
"""


def test_deadline_timer():
    units = implementation("deadline_timer.py", "units")
    for instant, calendar in (("2026-11-19T23:00:00Z", "2026-11-19 23:00:00 UTC"),
                              ("2028-02-29T00:00:05Z", "2028-02-29 00:00:05 UTC")):
        assert units(instant) == {
            "rezono-deadline.timer": TIMER.format(calendar=calendar).encode(),
            "rezono-deadline.service": SERVICE.encode(),
        }
    for instant in ("2026-11-19T23:00:00+01:00", "2026-11-19T23:00:00+00:00", "2026-11-19T23:00:00",
                    "2026-11-19T23:00:00.5Z", "2026-02-29T00:00:00Z", "2026-11-19T24:00:00Z",
                    "2026-11-19 23:00:00Z", ""):
        with pytest.raises(ValueError):
            units(instant)
