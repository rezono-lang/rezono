from datetime import date
import json
from pathlib import Path

import pytest

from query_fixture import ROOT


def test_support_window_uses_explicit_inclusive_dates():
    from rezono_compiler import scenarios
    from rules_support import State, states

    model, prog, _ = states(ROOT)
    label, raw = next(iter(scenarios.states(model, ROOT)))
    source = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["kubernetes"]
    name = "support_window_result"
    assert name in prog.relations, "Missing parameterized support-window relation"
    end = date.fromisoformat(source["end"])
    epoch = date(1970, 1, 1)
    for day, horizon in (("2026-02-01", 26), ("2026-02-01", 27), ("2026-02-28", 0), ("2026-03-01", 30)):
        as_of = date.fromisoformat(day)
        query = {"support_query": [("query",)], "support_query__as_of_day": [("query", (as_of - epoch).days)],
                 "support_query__horizon_days": [("query", horizon)]}
        result = State(model, prog, label, raw | query).derived[name]
        expected = {("query", "cp", "1.32.13", source["end"], source["url"], source["sha256"])}
        assert result == (expected if 0 <= (end - as_of).days <= horizon else set()), (day, horizon)
