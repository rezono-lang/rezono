"""The shapes of a name and of a date the compiler accepts, defined once (RV-M01)."""

import re

# A name: snake_case, no '__' (reserved as the separator of `kind__slot`).
NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
# A date as text: ISO 8601, `YYYY-MM-DD`. The shape only; whether the day exists is the caller's check.
ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
