"""Small test adapters. Expected rows come from the independent platform example."""

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def evidence():
    rows = json.loads((ROOT / "oracle-rows.json").read_text())
    facts = yaml.safe_load((ROOT / "facts/core.yaml").read_text())
    return rows, facts


def check_relation(name, expected):
    from rules_support import states

    _, _, fact_states = states(ROOT)
    state, = fact_states
    assert name in state.derived, f"Missing derived relation: {name}"
    assert state.derived[name] == {tuple(str(value) for value in row) for row in expected}


def portal_template(name):
    path = ROOT / "portal" / (name + ".py")
    assert path.is_file(), f"Missing public rendering module: {name}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
