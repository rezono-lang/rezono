from datetime import date
import json
from pathlib import Path

import pytest

from query_fixture import ROOT


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Waits for compiler/tests/test_rule_day_numbers.py--test_rules_read_a_text_date_as_a_day_number (#718): "
    "rules cannot yet turn the published text date into a day number. "
    "Then derive support_window_result(query, service, version, end, url, sha256) in rules/support_window.dl from "
    "published_series_support. Declare SupportQuery (as_of_day, horizon_days: integers the caller supplies, no "
    "fact rows) and SupportedServiceRelease (service: Service, product: Product, series, version) in "
    "schema/support_window.yaml, and write the one binding {id: cp-kubernetes-1.32.13, service: cp, product: "
    "kubernetes, series: '1.32', version: 1.32.13} in facts/support_window.yaml; its standalone violations are "
    "pinned in expected/violations/support_window.json. Both bounds are inclusive. "
    "Read decisions/platform-source-and-scenario-cases.md."))
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
