"""Coverage certificates must follow the recorded node inventory and reports."""

import pytest

from flow_drift_cases import REPORT_CASES, SCOPE, SWEEP_COLUMNS, SWEEP_REF, coverage_rows
from loop_oracle import evaluate


def test_complete_flow_sweep():
    for case in (*REPORT_CASES, "empty-inventory"):
        expected = {(*SCOPE, SWEEP_REF)} if case == "complete" else set()
        assert evaluate("complete_sweep", SWEEP_COLUMNS, coverage_rows(case)) == expected, case
