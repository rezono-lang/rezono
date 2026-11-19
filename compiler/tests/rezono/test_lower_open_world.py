"""An open kind and an open slot must lower to the `world: open` annotations of the public schemas."""

import pytest
import yaml

from model_parity import kind, lower_declarations, schema_file, slot


def world(definition):
    return (definition.get("annotations") or {}).get("world", "closed")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="M3: Lower world open on a kind and on a slot to the LinkML annotation world: open instead of refusing it, "
           "in compiler/rezono_compiler/rezono_kind.py and rezono_slot.py, and update docs/rezono/publication.md 5.1. "
           "Read decisions/language-relations.md and docs/rezono/v0.md (world open). Waits for test_lower_time_policy "
           "while it owns rezono_kind.py and for test_lower_extended_scalar while it owns rezono_slot.py.",
)
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
