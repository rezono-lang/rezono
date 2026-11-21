"""Retire `SupportQuery.as_of_day` in favour of a native `date` slot (`as_of`)
(decisions/standard-packs-everywhere.md, sections 1.1, 1.2 and 1.4 step 5;
decisions/no-green-by-cheapest-route.md).
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parent
SCHEMA = PLATFORM / "schema" / "support_window.yaml"
WINDOWS = (("2026-02-01", 26), ("2026-02-01", 27), ("2026-02-28", 0), ("2026-03-01", 30))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M3: decisions/standard-packs-everywhere.md: sections 1.1, 1.2 and 1.4 step 5. "
           "Retire SupportQuery.as_of_day from examples/platform/schema/support_window.yaml, "
           "replace it with a required native `date` slot `as_of`, and make "
           "examples/platform/rules/support_window.dl compute the inclusive support window from "
           "`support_query__as_of` via `@days` instead of reading an integer day number "
           "(decisions/no-green-by-cheapest-route.md). "
           "Waits for compiler/tests/test_std_decision_dates.py--test_std_decision_rules_read_dates.",
)
def test_support_query_retires_as_of_day_for_native_date():
    doc = yaml.safe_load(SCHEMA.read_text(encoding="utf-8")) or {}
    attrs = ((doc.get("classes") or {}).get("SupportQuery") or {}).get("attributes") or {}

    day_numbers = sorted(slot for slot in attrs if slot.endswith("_day"))
    assert not day_numbers, f"SupportQuery still keeps integer day-number slots: {day_numbers}"
    as_of_slot = attrs.get("as_of") or {}
    assert as_of_slot.get("range") == "date" and as_of_slot.get("required") is True, (
        f"SupportQuery.as_of must be a required native date slot, got {as_of_slot!r}"
    )

    from rezono_compiler import pack, rules, scenarios
    from rules_support import State, states

    model = pack.read(PLATFORM)
    used = set(rules.load(model.rules).base_used())
    assert "support_query__as_of_day" not in used, "platform rules still read support_query__as_of_day"
    assert "support_query__as_of" in used, "platform rules must read native date slot support_query__as_of"

    # Independent boundary check using native ISO dates (no epoch day-number integer conversion).
    source = json.loads((PLATFORM / "acceptance" / "product-evidence.json").read_text(encoding="utf-8"))["kubernetes"]
    end = date.fromisoformat(source["end"])
    model, prog, _ = states(PLATFORM)
    label, raw = next(iter(scenarios.states(model, PLATFORM)))
    for day, horizon in WINDOWS:
        query = {
            "support_query": [("query",)],
            "support_query__as_of": [("query", day)],
            "support_query__horizon_days": [("query", horizon)],
        }
        got = State(model, prog, label, raw | query).derived["support_window_result"]
        expected = {("query", "cp", "1.32.13", source["end"], source["url"], source["sha256"])}
        inside = 0 <= (end - date.fromisoformat(day)).days <= horizon
        assert got == (expected if inside else set()), (day, horizon)
