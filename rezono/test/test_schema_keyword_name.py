"""A schema named like a keyword is written in backticks; bare, the keyword is refused where a name is expected."""

import json

import pytest

from reader_probe import at, read_modules

HEADER = "rezono 0\npack sample\n"
BARE = HEADER + "schema example\n"
QUOTED = HEADER + "schema `example`\n  iri \"urn:example:example\"\n"


class MissingBacktickedSchemaName(AssertionError):
    """The reader refused a schema name in backticks, or did not read or print it as the exact name."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingBacktickedSchemaName,
    reason="extra: decisions/language-metadata.md: In rezono/src/module-metadata.ts, read a schema name in backticks "
           "as the exact name between them, so that schema `example` holds schema example, and print a schema "
           "name that is a keyword in backticks again. Keep refusing a bare keyword with R000. Read section A "
           "keyword as a schema name.",
)
def test_schema_keyword_name():
    bare, quoted = read_modules(BARE, QUOTED)
    # The counter-case holds before and after: `example` is a keyword, so it is no bare name.
    assert bare["module"] is None, bare
    assert bare["diagnostics"] == [{"code": "R000", "span": at(BARE, "example", "schema ")}], bare
    module = quoted["module"] or {}
    if quoted["diagnostics"] or module.get("schema") != "example" or quoted["printed"] != QUOTED:
        raise MissingBacktickedSchemaName(json.dumps(quoted, indent=2))
