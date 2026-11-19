"""A deprecated line above a kind or an enum belongs to that declaration (decisions/language-deprecation.md).
The expected members are copied from that decision."""

import json

import pytest

from reader_probe import read_modules

HEADER = "rezono 0\npack sample\n"
ZONE = "kind Zone world closed\n  name: Text\n"
MODE = "enum Mode = audit | enforce\n"
SOURCE = (HEADER + 'deprecated "use ProviderZone" until 2027-07-01\n' + ZONE
          + 'deprecated "use PolicyMode" until 2028-01-31\n' + MODE)


class MissingDeprecatedDeclaration(AssertionError):
    """The module reader did not read, print or refuse a deprecated line as the decision gives it."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingDeprecatedDeclaration,
    reason="extra: decisions/language-deprecation.md: Read a line deprecated \"TEXT\" until DATE directly above a "
           "kind or an enum as the member deprecated: {note, until} of that declaration in rezono/src/module.ts, "
           "print it back above its declaration, refuse the forms of the section Reading, and admit the member in "
           "rezono.module/2 in contracts/rezono-module.yaml. Read the sections Reading and Format and meaning.",
)
def test_deprecated_declaration():
    plain, read, *refused = read_modules(
        HEADER + ZONE + MODE,
        SOURCE,
        HEADER + 'deprecated "use ProviderZone"\n' + ZONE,  # no date
        HEADER + 'deprecated "use ProviderZone" until 2027-07-01\n',  # no declaration under it
        HEADER + 'deprecated "use ProviderZone" until 2027-07-01\n\n' + ZONE,  # a blank line between
        HEADER + 'deprecated "a" until 2027-07-01\ndeprecated "b" until 2027-07-01\n' + ZONE,  # twice
        HEADER + 'deprecated "use ProviderZone" until 2027-02-30\n' + ZONE,  # no day of the calendar
    )
    # Counter-case: the declarations without the line keep their members, before and after.
    assert [sorted(d) for d in plain["module"]["decls"]] == [["derived", "kind", "slots", "world"],
                                                              ["enum", "values"]], plain
    problems = []
    expected = [dict(plain["module"]["decls"][0], deprecated={"note": "use ProviderZone", "until": "2027-07-01"}),
                dict(plain["module"]["decls"][1], deprecated={"note": "use PolicyMode", "until": "2028-01-31"})]
    if read["diagnostics"] or read["module"]["decls"] != expected or read["printed"] != SOURCE:
        problems.append(read)
    for refusal, code in zip(refused, ("R000", "R000", "R000", "R000", "R012")):
        if refusal["module"] is not None or code not in [d["code"] for d in refusal["diagnostics"]]:
            problems.append(refusal)
    if problems:
        raise MissingDeprecatedDeclaration(json.dumps(problems, indent=2))
