"""An open kind and an open slot must lower to the `world: open` annotations of the public schemas."""

import pytest
import yaml

from model_parity import kind, lower_declarations, schema_file, slot


def world(definition):
    return (definition.get("annotations") or {}).get("world", "closed")


def test_lower_open_world(tmp_path):
    # The LinkML spelling of an open kind, as the compiler reads it (docs/compiler/rules.md, world).
    statement = yaml.safe_load("{annotations: {world: open}, attributes: {holder: {range: Holder, required: true}}}")
    declaration = kind("Statement", slot("holder", "Holder"), world="open")
    actual = lower_declarations(tmp_path, "sample", [declaration], external=["Holder"])["classes"]["Statement"]
    assert world(actual) == world(statement) == "open"

    decision = schema_file("packs/std-decision/schema/decision.yaml")["classes"]["Decision"]["attributes"]
    declaration = kind("Decision", slot("subject", "Text"), slot("decider", "Text", world="open"))
    actual = lower_declarations(tmp_path, "std-decision", [declaration])["classes"]["Decision"]
    assert world(actual) == "closed"
    assert world(actual["attributes"]["decider"]) == world(decision["decider"]) == "open"
    assert world(actual["attributes"]["subject"]) == world(decision["subject"]) == "closed"
