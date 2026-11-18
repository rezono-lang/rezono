"""The platform publishes one main state assembled from every authored fact file."""

from pathlib import Path

from rezono_compiler import pack, scenarios
from support import compile_dir, violations

PLATFORM = Path(__file__).resolve().parent


def test_main_fact_state_has_no_integrity_violations(tmp_path):
    # A fragment may refer to a target in another file. Every reference in the
    # published state must resolve, and repeated identifiers must remain visible.
    states = scenarios.fact_states(pack.read(PLATFORM), PLATFORM, diagnostics=False)
    rows, = [rows for kind, _, _, rows in states if kind == "facts"]
    assert violations(compile_dir(PLATFORM, tmp_path), rows) == {}
