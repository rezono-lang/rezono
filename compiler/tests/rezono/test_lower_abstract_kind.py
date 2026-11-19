import pytest

from model_parity import compare_input, kind, slot


def test_lower_abstract_kind(tmp_path):
    decl = kind("Person", slot("name", "Text"), abstract=True)
    actual, oracle = compare_input(tmp_path, "library", decl)
    assert actual["classes"]["Person"].get("abstract", False) == oracle["classes"]["Person"]["abstract"]
