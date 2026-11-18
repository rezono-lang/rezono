"""Named keys are typed declarations in the extended module format."""

from pathlib import Path

import pytest
from linkml.validator import validate
from linkml_runtime import SchemaView


SCHEMA = str(Path(__file__).resolve().parents[2] / "rezono-module.yaml")
KIND = {
    "kind": "Category",
    "slots": [{"slot": "parent", "type": "Category", "card": "?"}, {"slot": "name", "type": "Text"}],
    "derived": [],
}
KEY = {"unique": "name_within_parent", "slots": ["parent", "name"]}


def errors(version, kind):
    document = {
        "format": f"rezono.module/{version}",
        "module": {"rezono": "0", "pack": "sample", "use": [], "decls": [kind]},
        "spans": [],
    }
    return validate(document, SCHEMA, "ModuleForm").results


def test_composite_keys_are_version_two_only():
    assert not errors(1, KIND)
    assert not errors(2, KIND)
    with_keys = {**KIND, "keys": [KEY, {"unique": "reverse", "slots": ["name", "parent"]}]}
    assert not errors(2, with_keys)
    assert errors(1, with_keys)


@pytest.mark.parametrize(
    "keys",
    [
        [],
        KEY,
        [{"slots": KEY["slots"]}],
        [{"unique": KEY["unique"]}],
        [{**KEY, "unique": "NotAName"}],
        [{**KEY, "unique": ["pair", "pair"]}],
        [{**KEY, "slots": []}],
        [{**KEY, "slots": "parent"}],
        [{**KEY, "slots": ["parent", 3]}],
        [{**KEY, "extra": True}],
    ],
)
def test_composite_keys_reject_malformed_declarations(keys):
    assert errors(2, {**KIND, "keys": keys})


def test_composite_key_schema_declares_unique_names_and_distinct_slots():
    schema = SchemaView(SCHEMA)
    assert schema.get_identifier_slot("CompositeKey").name == "unique"
    assert schema.induced_slot("keys", "KindDeclWithKeys").list_elements_unique
    assert schema.induced_slot("slots", "CompositeKey").list_elements_unique
