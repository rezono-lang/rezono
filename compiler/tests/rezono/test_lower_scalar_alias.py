import pytest

from model_parity import compare_input


def test_lower_scalar_alias(tmp_path):
    decl = {"type": "Cents", "base": "Int"}
    actual, oracle = compare_input(tmp_path, "projects", decl)
    assert actual.get("types", {}).get("Cents", {}).get("typeof") == oracle["types"]["Cents"]["typeof"]
