"""A schema named like a keyword is written in backticks; bare, the keyword is refused where a name is expected."""

import json

import pytest

from reader_probe import at, read_modules

HEADER = "rezono 0\npack sample\n"
BARE = HEADER + "schema where\n"
QUOTED = HEADER + "schema `where`\n  iri \"urn:example:where\"\n"


class MissingBacktickedSchemaName(AssertionError):
    """The reader refused a schema name in backticks, or did not read or print it as the exact name."""


def test_schema_keyword_name():
    bare, quoted = read_modules(BARE, QUOTED)
    # The counter-case holds before and after: `where` is a hard expression keyword, so it is no bare name.
    assert bare["module"] is None, bare
    assert bare["diagnostics"] == [{"code": "R000", "span": at(BARE, "where", "schema ")}], bare
    module = quoted["module"] or {}
    if quoted["diagnostics"] or module.get("schema") != "where" or quoted["printed"] != QUOTED:
        raise MissingBacktickedSchemaName(json.dumps(quoted, indent=2))
