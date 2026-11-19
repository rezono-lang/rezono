"""The pack converter reads an enum member that a LinkML schema writes without a body."""

from pathlib import Path

import pytest

from scripts.convert_pack import ConversionError, sources


class MissingBodilessEnumMember(AssertionError):
    """The converter refused an enum member that YAML reads as null."""


def schema(directory: Path, members: str) -> None:
    path = directory / "schema/listing.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "id: https://rezono.example/sample/listing\n"
        "name: listing\n"
        "imports: [linkml:types]\n"
        "default_range: string\n"
        "annotations: {layer: facts}\n"
        "enums:\n"
        "  State:\n"
        "    permissible_values:\n"
        f"{members}"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      state: {range: State, required: true}\n",
        encoding="utf-8",
    )


def test_bodiless_enum_member_converts_like_an_empty_one(tmp_path):
    bare, empty = tmp_path / "bare", tmp_path / "empty"
    schema(bare, "      pending:\n      ready:\n        description: the item can be read\n")
    schema(empty, "      pending: {}\n      ready:\n        description: the item can be read\n")
    expected = sources(empty, "sample")["listing"].lines
    try:
        converted = sources(bare, "sample")["listing"].lines
    except ConversionError as error:
        if "State.pending: expected a named mapping" not in str(error):
            raise
        raise MissingBodilessEnumMember(str(error)) from error
    assert "enum State world closed = pending | ready" in converted
    assert converted == expected
