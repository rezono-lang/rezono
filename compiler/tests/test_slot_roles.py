"""S26's compiler metadata: roles are typed, unambiguous and inherited, never guessed from names."""

import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, pack
from support import FIXTURE


ROLES = {
    "name": ("string", "rdfs:label", "http://www.w3.org/2000/01/rdf-schema#label"),
    "description": ("string", "schema:description", "http://schema.org/description"),
    "image": ("string", "schema:image", "http://schema.org/image"),
    "order": ("integer", "schema:position", "http://schema.org/position"),
    "valid_from": ("date", "schema:validFrom", "http://schema.org/validFrom"),
    "valid_until": ("date", "schema:validThrough", "http://schema.org/validThrough"),
    "known_from": ("date", "prov:generatedAtTime", "http://www.w3.org/ns/prov#generatedAtTime"),
}
PREFIXES = {"rdfs": "http://www.w3.org/2000/01/rdf-schema#", "schema": "http://schema.org/",
            "sdo": "https://schema.org/", "prov": "http://www.w3.org/ns/prov#"}
URIS = [(role, uri) for role, (_, curie, iri) in ROLES.items()
        for uri in ([curie, iri, iri.replace("http://schema.org/", "https://schema.org/")]
                    if iri.startswith("http://schema.org/") else [curie, iri])]


@pytest.fixture
def fixture(tmp_path):
    return shutil.copytree(FIXTURE, tmp_path / "pack")


def edit(fixture, change):
    path = fixture / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["prefixes"] = PREFIXES
    change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False))


def role_slot(role, uri=None, **facets):
    rng, curie, _ = ROLES[role]
    return {"range": rng, "slot_uri": uri or curie, **facets}


@pytest.mark.parametrize("role,uri", URIS)
def test_curie_and_full_iri_roles_are_inherited_in_the_bundle(fixture, role, uri):
    def change(s):
        s["classes"]["Alpha"]["attributes"]["role_value"] = role_slot(role, uri)
        s["classes"]["Gamma"] = {"is_a": "Alpha", "attributes": {"note": {}}}
    edit(fixture, change)
    model = pack.read(fixture)
    kinds = {k["id"]: k for k in emit.bundle(model, [])["kinds"]}
    for kind in ("alpha", "gamma"):
        assert kinds[kind]["slot_roles"] == {role: "alpha.role_value"}
        if role == "name":
            assert kinds[kind]["name_attribute"] == "alpha.role_value"
        else:
            assert "name_attribute" not in kinds[kind]


def test_a_declared_prefix_alias_resolves_by_iri(fixture):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"].update(
        detail=role_slot("description", "sdo:description")))
    assert pack.read(fixture).slot_roles("alpha")["description"].element == "alpha.detail"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("inherited", [False, True])
def test_a_second_slot_with_the_same_role_is_refused(fixture, role, inherited):
    def change(s):
        s["classes"]["Alpha"]["attributes"]["first"] = role_slot(role)
        kind = "Alpha"
        if inherited:
            kind = "Gamma"
            s["classes"][kind] = {"is_a": "Alpha", "attributes": {}}
        s["classes"][kind]["attributes"]["second"] = role_slot(role)
    edit(fixture, change)
    with pytest.raises(pack.CompileError, match=f"more than one {role}"):
        pack.read(fixture)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("facets", [{"range": "boolean"}, {"range": "Alpha"},
                                    {"range": "State"}, {"multivalued": True}])
def test_a_role_must_be_one_attribute_of_its_declared_type(fixture, role, facets):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"].update(
        role_value=role_slot(role, **facets)))
    with pytest.raises(pack.CompileError, match="one .* value, not an arrow, enum or list"):
        pack.read(fixture)


@pytest.mark.parametrize("role", ["valid_from", "valid_until", "known_from"])
def test_datetime_remains_refused_until_the_engine_types_timestamps(fixture, role):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"].update(
        role_value=role_slot(role, range="datetime")))
    with pytest.raises(pack.CompileError, match="type 'datetime' is not supported"):
        pack.read(fixture)


@pytest.mark.parametrize("uri", ["not_declared:position", "https://example.invalid/position"])
def test_an_unrecognised_uri_has_no_role(fixture, uri):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["size"].update(slot_uri=uri))
    model = pack.read(fixture)
    assert model.slot_roles("alpha") == {}
    assert "slot_roles" not in next(k for k in emit.bundle(model, [])["kinds"] if k["id"] == "alpha")


def test_roles_change_metadata_without_changing_engine_sql(fixture):
    before = emit.compile_pack(pack.read(fixture))
    edit(fixture, lambda s: (s["classes"]["Alpha"]["attributes"]["title"].update(slot_uri="rdfs:label"),
                            s["classes"]["Alpha"]["attributes"]["size"].update(slot_uri="schema:position")))
    after = emit.compile_pack(pack.read(fixture))
    assert {p: v for p, v in before.items() if p.endswith(".sql")} == {
        p: v for p, v in after.items() if p.endswith(".sql")}
    kind = next(k for k in json.loads(after["bundle/schema-bundle.json"])["kinds"] if k["id"] == "alpha")
    assert kind["slot_roles"] == {"name": "alpha.title", "order": "alpha.size"}


def test_a_role_can_use_an_existing_derived_scalar_type(fixture):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["size"].update(slot_uri="schema:position"))
    assert pack.read(fixture).slot_roles("alpha")["order"].sql_type == "BIGINT"  # Count derives from integer
