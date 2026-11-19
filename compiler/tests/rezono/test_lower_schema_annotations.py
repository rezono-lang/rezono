"""Kind and slot annotations must lower to the same LinkML annotations as the public pack schemas."""

import pytest

from model_parity import kind, lower_declarations, schema_file, slot


def values(annotations):
    """LinkML writes an annotation as its value or as {value: ...}; both state the same value."""
    return {name: value["value"] if isinstance(value, dict) and set(value) == {"value"} else value
            for name, value in (annotations or {}).items()}


def test_lower_schema_annotations(tmp_path):
    axis = schema_file("packs/std-time/schema/time.yaml")["classes"]["Axis"]
    declaration = kind("Axis", annotations={"explain": "fold"})
    actual = lower_declarations(tmp_path, "std-time", [declaration])["classes"]["Axis"]
    assert values(actual.get("annotations")) == values(axis["annotations"])

    offer = schema_file("run/packs/offer-selection/schema/offers.yaml")["classes"]["Offer"]
    # The module form writes numbers as exact decimal text (decisions/language-metadata.md).
    explore = {"min": "499", "max": "501", "step": "1"}
    declaration = kind("Offer", slot("period_price_minor", "Int", card="?", annotations={"explore": explore}))
    actual = lower_declarations(tmp_path, "offer-selection", [declaration])["classes"]["Offer"]
    expected = offer["attributes"]["period_price_minor"]["annotations"]
    assert values(actual["attributes"]["period_price_minor"].get("annotations")) == values(expected)
