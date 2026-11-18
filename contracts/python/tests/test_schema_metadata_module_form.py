"""The module form preserves authored schema and declaration metadata."""

from pathlib import Path

import pytest
from linkml.validator import validate

SCHEMA = str(Path(__file__).resolve().parents[2] / "rezono-module.yaml")


@pytest.fixture
def document():
    return {
        "format": "rezono.module/2",
        "module": {
            "rezono": "0",
            "pack": "sample",
            "use": [],
            "schema": "field_notes",
            "iri": "urn:example:field-notes",
            "language": "en",
            "prefixes": {"rdfs": "http://www.w3.org/2000/01/rdf-schema#"},
            "imports": ["urn:example:references", "linkml:types"],
            "defaultRange": "Text",
            "description": "Recording field observations.",
            "annotations": {"layer": "facts"},
            "decls": [
                {
                    "kind": "Observation",
                    "world": "closed",
                    "description": "An observation made outdoors.",
                    "slots": [
                        {
                            "slot": "caption",
                            "type": "Text",
                            "slotUri": "rdfs:label",
                            "description": "A brief label.",
                        },
                        {"slot": "detail", "type": "Text", "card": "?"},
                    ],
                    "derived": [],
                },
                {
                    "enum": "Evidence",
                    "world": "closed",
                    "values": ["sketch", "photo"],
                    "description": "How the observation was recorded.",
                    "memberMetadata": {"photo": {"description": "A photograph taken on site."}},
                },
            ],
        },
        "spans": [
            {"at": "", "line": "3", "start": "28", "end": "39"},
            {"at": "/decls/1/memberMetadata/photo", "line": "20", "start": "560", "end": "565"},
        ],
    }


def errors(document):
    return [item.message for item in validate(document, SCHEMA, "ModuleForm").results]


def at(document, path):
    target = document
    for key in path:
        target = target[key]
    return target


def test_version_two_accepts_the_written_metadata(document):
    assert errors(document) == []
    module = document["module"]
    module["annotations"]["quality"] = {"flags": [True, [False, {"score": "-2.00"}]]}
    module["decls"][0]["slots"][0]["exactMappings"] = ["other:label", "urn:example:caption"]
    module["decls"][1]["memberMetadata"]["photo"]["annotations"] = {"portable": True}
    assert errors(document) == []


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        ((), "extra", "unknown"),
        (("module",), "extra", "unknown"),
        (("module",), "schema", None),
        (("module",), "defaultRange", "attr"),
        (("module",), "imports", "linkml:types"),
        (("module", "prefixes"), "wrong", {"iri": "urn:example:wrong"}),
        (("module", "annotations"), "wrong", {"score": 2}),
        (("module", "annotations"), "wrong", [None]),
        (("module", "decls", 0), "extra", "unknown"),
        (("module", "decls", 0, "slots", 0), "extra", "unknown"),
        (("module", "decls", 0, "slots", 0), "slotUri", ["rdfs:label"]),
        (("module", "decls", 0, "slots", 0), "exactMappings", [False]),
        (("module", "decls", 1), "extra", "unknown"),
        (("module", "decls", 1, "memberMetadata"), "sketch", "wrong"),
        (("module", "decls", 1, "memberMetadata", "photo"), "extra", "unknown"),
    ],
)
def test_version_two_rejects_unknown_fields_and_malformed_metadata(document, path, key, value):
    at(document, path)[key] = value
    assert errors(document)


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        (("module",), "schema", "field_notes"),
        (("module",), "description", "Observations."),
        (("module", "decls", 0), "annotations", {"portable": True}),
        (("module", "decls", 0, "slots", 0), "slotUri", "rdfs:label"),
        (("module", "decls", 0, "slots", 0), "exactMappings", ["other:label"]),
        (("module", "decls", 1), "description", "Evidence."),
        (("module", "decls", 1), "memberMetadata", {"photo": {"description": "A photograph."}}),
    ],
)
def test_version_one_keeps_the_legacy_shape(document, path, key, value):
    kind, enum = document["module"]["decls"]
    del kind["description"], kind["slots"][0]["description"], kind["slots"][0]["slotUri"]
    del enum["description"], enum["memberMetadata"]
    legacy = {
        "format": "rezono.module/1",
        "module": {name: document["module"][name] for name in ("rezono", "pack", "use", "decls")},
        "spans": [{"at": "/decls/0", "line": "12", "start": "301", "end": "312"}],
    }
    assert errors(legacy) == []
    at(legacy, path)[key] = value
    assert errors(legacy)


def test_the_empty_module_pointer_requires_version_two(document):
    document["module"] = {"pack": "sample", "use": [], "decls": []}
    document["spans"] = document["spans"][:1]
    assert errors(document) == []
    document["format"] = "rezono.module/1"
    assert errors(document)
