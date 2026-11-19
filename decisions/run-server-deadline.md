# A deadline clock on every rented machine

A run must be cleaned up on the day it starts. The rule side already reports an applied run that is still not cleaned up at its deadline. That finding needs someone to act. The guarantee also needs enforcement that does not depend on the runner, the network or the loop staying alive: a clock on the machine itself, and a low resource quota at the provider.

## Decision

Every machine receives two systemd units in its boot data. At the approved cleanup deadline the timer starts a service that powers the machine off.

`run/deadline_timer.py:units(deadline)` takes the deadline as a UTC instant of exactly the form `YYYY-MM-DDThh:mm:ssZ`, such as `2026-11-19T23:00:00Z`. It returns a mapping from file name to bytes:

`rezono-deadline.timer`

```ini
[Unit]
Description=Power off at the run cleanup deadline

[Timer]
OnCalendar=2026-11-19 23:00:00 UTC
AccuracySec=1s
Persistent=true

[Install]
WantedBy=timers.target
```

`rezono-deadline.service`

```ini
[Unit]
Description=Power off at the run cleanup deadline

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl poweroff
```

Both files end with one newline. Only the `OnCalendar` value varies. `Persistent=true` makes a machine that boots after its deadline power off at once. Raise `ValueError` for any other form, including an offset written as `+00:00`, a missing offset, a space instead of `T`, fractional seconds, or a date or time that does not exist.

Powering off does not end billing; at the chosen provider charges continue until the machine is destroyed. The clock bounds what the machine can still do after the deadline. Destruction remains the cleanup step, proven by a complete inventory, and the overdue finding still applies. The low provider quota remains the operator's first action in the [operator guide](../run/OPERATOR.md).

## Alternatives

A timer in the runner or the loop disappears with the runner. A provider-side scheduled deletion would need a provider feature and a credential on the machine. A shutdown command with a relative delay restarts its count on every boot.
