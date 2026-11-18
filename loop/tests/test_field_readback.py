"""Recover a typed knowledge field through its original render binding."""

from pathlib import Path
from runpy import run_path

import pytest


def test_field_readback():
    read_field = run_path(str(Path(__file__).resolve().parents[1] / "field_readback.py"))["read_field"]
    binding = {"origin": "knowledge", "pointer": "/spec/a~1b/0", "column": "count",
               "witness": {"relation": "replicas", "key": '["echo"]'}, "type": "integer"}
    obj = {"spec": {"a/b": [3]}}
    assert read_field(binding, obj) == (binding["witness"], "count", 3)
    with pytest.raises(ValueError):
        read_field(binding, {"spec": {"a/b": ["3"]}})
    assert read_field({"origin": "chart_constant", "pointer": "/spec"}, obj) is None
