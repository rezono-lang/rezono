"""The pack converter accepts a rules file whose stem names no schema module."""

import os
from pathlib import Path

import pytest
import yaml

from scripts.convert_pack import ConversionError, candidate


class MissingRuleOnlyModule(AssertionError):
    """The candidate comparison refused a native module that only holds rules."""


MESSAGES = ("arrow.total", "arrow.partial", "attribute.total", "attribute.partial", "is_a", "unique_key",
            "path_equation")

FILES = {
    "pack.yaml": "name: sample\nversion: '0'\ndefault_language: en\nimports: []\n",
    "channels.yaml": "kinds:\n  - {kind: item, shape: rect}\n",
    "labels/en.yaml": "item: item\nitem.state: state\nstate: state\nstate.pending: pending\nstate.ready: ready\n"
                      "seen: seen item\n",
    "messages/en.mf2": "@locale en\n---\n" + "".join(f"{key} = {key}\n" for key in MESSAGES),
    "schema/listing.yaml": (
        "id: https://rezono.example/sample/listing\n"
        "name: listing\n"
        "imports: [linkml:types]\n"
        "default_range: string\n"
        "annotations: {layer: facts}\n"
        "enums:\n"
        "  State:\n"
        "    permissible_values: {pending: {}, ready: {}}\n"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      state: {range: State, required: true}\n"
    ),
    "rules/seen.dl": ".decl seen(item: symbol)\nseen(x) :- item(x).\n.output seen\n",
}


def sample(directory: Path) -> Path:
    for relative, text in FILES.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return directory


def test_rules_file_without_a_schema_of_its_name_converts(tmp_path):
    original = sample(tmp_path / "sample")
    destination = tmp_path / "trial"
    try:
        candidate(original, destination, os.environ.get("REZONO_NODE", "node"))
    except ConversionError as error:
        if str(error) != "the candidate changed the schema or module identity":
            raise
        raise MissingRuleOnlyModule(str(error)) from error
    meta = yaml.safe_load((destination / "pack.yaml").read_bytes())
    assert [entry["module"] for entry in meta["rezono"]] == ["rezono/listing.rezono", "rezono/seen.rezono"]
    assert "rules seen" in (destination / "rezono/seen.rezono").read_text(encoding="utf-8").splitlines()
    assert not (destination / "rules/seen.dl").exists()
