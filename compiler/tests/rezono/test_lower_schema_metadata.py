"""Schema metadata from a hand-written module, checked against the std-access LinkML schema."""

import json
from pathlib import Path

import pytest
import yaml

from rezono_compiler import emit, modules, pack
from support import FIXTURE

STD_ACCESS = Path(__file__).resolve().parents[3] / "packs" / "std-access"
TITLE_DESCRIPTION = "The label of a role at the gate."
FORM = {
    "format": "rezono.module/2",
    "module": {
        "rezono": "0",
        "pack": "std-access",
        "use": [],
        "schema": "std_access",
        "iri": "https://rezono.example/std-access/access",
        "language": "en",
        "prefixes": {
            "linkml": "https://w3id.org/linkml/",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        },
        "imports": ["linkml:types"],
        "defaultRange": "Text",
        "description": (
            "Roles in two layers. A role is an element like any other: the pack names its roles as facts, "
            "and its rules derive which typed elements a role may read, as may_read(role, kind, element). "
            "Rezono knows only the generic capabilities below; a pack maps each of its roles to capabilities "
            "as facts (role__capability), and its read rules may grant a kind to every role that holds a capability."
        ),
        "decls": [{
            "kind": "Role",
            "world": "closed",
            "description": "A role at the gate, as the deploy profile names it (access.roles).",
            "slots": [
                {"slot": "id", "type": "Text", "identifier": True, "card": "?"},
                {"slot": "title", "type": "Text", "description": TITLE_DESCRIPTION, "slotUri": "rdfs:label"},
            ],
            "derived": [],
        }],
    },
    "spans": [
        {"at": path, "line": "1", "start": "0", "end": "1"}
        for path in ("/decls/0", "/decls/0/slots/0", "/decls/0/slots/1", "/prefixes")
    ],
}


def schema_metadata(directory):
    errors = []
    loaded, _ = modules.load(directory, pack.read_meta(directory), errors)
    assert not errors, "\n".join(errors)
    [access] = loaded
    schema = access.sv.schema
    role = schema.classes["Role"]
    title = role.attributes["title"]
    return {
        "id": schema.id,
        "name": schema.name,
        "in_language": schema.in_language,
        "prefixes": {key: prefix.prefix_reference for key, prefix in schema.prefixes.items()},
        "imports": list(schema.imports),
        "default_range": schema.default_range,
        "description": schema.description,
        "role_description": role.description,
        "title_description": title.description,
        "title_uri": title.slot_uri,
    }


def published_role_name(directory):
    bundle = json.loads(emit.compile_pack(pack.read(directory))["bundle/schema-bundle.json"])
    [role] = [kind for kind in bundle["kinds"] if kind["id"] == "role"]
    assert any(attribute["id"] == "role.title" for attribute in bundle["attributes"])
    return role.get("name_attribute")


def test_lower_schema_metadata(tmp_path):
    legacy = tmp_path / "yaml" / "std-access"
    authored = tmp_path / "module" / "std-access"
    for directory in (legacy, authored):
        (directory / "labels").mkdir(parents=True)
        (directory / "labels/nl.yaml").write_text("role: rol\nrole.title: naam\n", encoding="utf-8")
        (directory / "messages").mkdir()
        for path in ("pack.yaml", "channels.yaml"):
            (directory / path).write_bytes((STD_ACCESS / path).read_bytes())
        (directory / "messages/nl.mf2").write_bytes((FIXTURE / "messages/nl.mf2").read_bytes())

    # Keep the public LinkML schema's Role and its two basic attributes. A slot description exercises
    # the same metadata path on a leaf without bringing capability enums and rules into this task.
    oracle = yaml.safe_load((STD_ACCESS / "schema/access.yaml").read_bytes())
    del oracle["enums"]
    attributes = oracle["classes"]["Role"]["attributes"]
    del attributes["capability"]
    title = attributes["title"]
    title["description"] = TITLE_DESCRIPTION
    (legacy / "schema").mkdir()
    yaml_schema = legacy / "schema/access.yaml"
    yaml_schema.write_text(yaml.safe_dump(oracle), encoding="utf-8")
    expected = schema_metadata(legacy)
    assert expected["title_uri"] == "rdfs:label"
    assert published_role_name(legacy) == "role.title"

    del title["slot_uri"]
    yaml_schema.write_text(yaml.safe_dump(oracle), encoding="utf-8")
    assert schema_metadata(legacy) == expected | {"title_uri": None}
    assert published_role_name(legacy) is None

    (authored / "rezono").mkdir()
    # Form-only input isolates the compiler's lowering from the source reader.
    (authored / "rezono/access.rezono").write_text("rezono 0\npack std-access\n", encoding="utf-8")
    form_path = authored / "rezono/access.json"
    form_path.write_text(json.dumps(FORM), encoding="utf-8")
    with (authored / "pack.yaml").open("a", encoding="utf-8") as manifest:
        manifest.write("rezono:\n  - module: rezono/access.rezono\n    form: rezono/access.json\n    layer: facts\n")

    assert schema_metadata(authored) == expected
    assert published_role_name(authored) == "role.title"

    without_label = json.loads(form_path.read_bytes())
    del without_label["module"]["decls"][0]["slots"][1]["slotUri"]
    form_path.write_text(json.dumps(without_label), encoding="utf-8")
    assert schema_metadata(authored) == expected | {"title_uri": None}
    assert published_role_name(authored) is None
