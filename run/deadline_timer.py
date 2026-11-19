"""The on-machine cleanup deadline clock, from decisions/run-server-deadline.md."""

import re
from datetime import datetime

_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

_TIMER = """[Unit]
Description=Power off at the run cleanup deadline

[Timer]
OnCalendar={calendar}
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
"""

_SERVICE = """[Unit]
Description=Power off at the run cleanup deadline

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl poweroff
"""


def units(deadline):
    """Return the systemd unit files that power the machine off at a UTC instant."""
    if not isinstance(deadline, str) or _INSTANT.fullmatch(deadline) is None:
        raise ValueError("deadline must be a UTC instant such as 2026-11-19T23:00:00Z")
    moment = datetime.strptime(deadline[:-1], "%Y-%m-%dT%H:%M:%S")
    calendar = moment.strftime("%Y-%m-%d %H:%M:%S") + " UTC"
    return {
        "rezono-deadline.timer": _TIMER.format(calendar=calendar).encode(),
        "rezono-deadline.service": _SERVICE.encode(),
    }
