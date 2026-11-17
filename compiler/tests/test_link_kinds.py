"""S27: a declared relationship is identified by its ends, never by a name attribute."""

import json

import pytest

from rede_compiler import emit, pack
from test_compiler import edit_schema, fixture, named, refused  # fixture shared with the minimal pack tests  # noqa: F401 (a pytest fixture)


def relationship(schema, ends=("omega", "alpha")):
    named(schema)
    beta = schema["classes"]["Beta"]
    beta["represents_relationship"] = True
    beta["attributes"]["omega"] = {"range": "Alpha", "required": True}
    beta["unique_keys"] = {"by_ends": {"unique_key_slots": list(ends)}} if ends else {}


@pytest.mark.parametrize("count", [2, 3])
def test_relationship_ends_keep_key_order_even_when_the_targets_have_the_same_kind(fixture, count):
    def change(schema):
        relationship(schema)
        if count == 3:
            beta = schema["classes"]["Beta"]
            beta["attributes"]["third"] = {"range": "Alpha", "required": True}
            beta["unique_keys"]["by_ends"]["unique_key_slots"].append("third")
    edit_schema(fixture, change)
    model = pack.read(fixture)
    beta = next(k for k in emit.bundle(model, [])["kinds"] if k["id"] == "beta")
    assert model.kinds["beta"].relationship
    assert beta["relationship"] is True
    assert beta["ends"] == ["beta.omega", "beta.alpha"] + (["beta.third"] if count == 3 else [])
    assert beta["name_arrows"] == beta["ends"]
    assert "name_attribute" not in beta


def test_a_relationship_skips_a_smaller_key_and_does_not_change_engine_sql(fixture):
    def change(schema):
        relationship(schema)
        schema["classes"]["Beta"]["unique_keys"]["a_smaller"] = {"unique_key_slots": ["alpha"]}
    edit_schema(fixture, change)
    marked = emit.compile_pack(pack.read(fixture))
    edit_schema(fixture, lambda s: s["classes"]["Beta"].pop("represents_relationship"))
    ordinary = emit.compile_pack(pack.read(fixture))
    assert {p: text for p, text in marked.items() if p.startswith("engine/")} == {
        p: text for p, text in ordinary.items() if p.startswith("engine/")}
    kinds = json.loads(marked["bundle/schema-bundle.json"])["kinds"]
    assert next(k for k in kinds if k["id"] == "beta")["ends"] == ["beta.omega", "beta.alpha"]
    assert all("relationship" not in k and "ends" not in k
               for k in json.loads(ordinary["bundle/schema-bundle.json"])["kinds"])


@pytest.mark.parametrize("inherit_marker", [True, False])
def test_a_relationship_uses_its_inherited_key_and_slot_ids(fixture, inherit_marker):
    def change(schema):
        relationship(schema)
        schema["classes"]["Gamma"] = {"is_a": "Beta"}
        if not inherit_marker:
            schema["classes"]["Beta"].pop("represents_relationship")
            schema["classes"]["Gamma"]["represents_relationship"] = True
    edit_schema(fixture, change)
    gamma = next(k for k in emit.bundle(pack.read(fixture), [])["kinds"] if k["id"] == "gamma")
    assert gamma["relationship"] is True
    assert gamma["ends"] == ["beta.omega", "beta.alpha"]


def test_an_explicit_false_overrides_an_inherited_relationship_marker(fixture):
    def change(schema):
        relationship(schema)
        schema["classes"]["Gamma"] = {"is_a": "Beta", "represents_relationship": False}
    edit_schema(fixture, change)
    gamma = next(k for k in emit.bundle(pack.read(fixture), [])["kinds"] if k["id"] == "gamma")
    assert "relationship" not in gamma and "ends" not in gamma


@pytest.mark.parametrize("ends, many", [
    ([], False), (["alpha"], False), (["alpha", "alpha"], False),
    (["omega", "alpha", "alpha"], False), (["state", "alpha"], False),
    (["omega", "alpha"], True),
])
def test_a_relationship_needs_at_least_two_distinct_single_valued_arrows(fixture, ends, many):
    def change(schema):
        relationship(schema, ends)
        if many:
            schema["classes"]["Beta"]["attributes"]["omega"]["multivalued"] = True
    edit_schema(fixture, change)
    refused(fixture, "represents_relationship needs a unique key of at least two distinct single-valued arrows")


@pytest.mark.parametrize("inherited", [False, True])
def test_a_relationship_cannot_have_an_own_or_inherited_name_attribute(fixture, inherited):
    def change(schema):
        relationship(schema)
        beta = schema["classes"]["Beta"]
        beta["attributes"]["caption"] = {"slot_uri": "rdfs:label"}
        if inherited:
            beta.pop("represents_relationship")
            schema["classes"]["Gamma"] = {"is_a": "Beta", "represents_relationship": True}
    edit_schema(fixture, change)
    refused(fixture, "represents_relationship forbids a name attribute")
