"""A header line that writes its default gives W107, and the form keeps every member as written
(decisions/language-readable-rules.md, section 3). The sources, spans and members are written from that decision."""

import json

import pytest
from reader_probe import at, read_modules

ZONE = "kind Zone world closed\n  name: Text\n"
SHORT = "rezono 0\npack sample\n\nschema sample\n  language en\n\n" + ZONE
FULL = ("rezono 0\npack sample\n\nschema sample\n  language en\n  import \"linkml:types\"\n  default range Text\n"
        "  annotation layer = \"facts\"\n\n" + ZONE)
# Counter-case: with another import, `linkml:types` is still needed in rezono 0 and gives no warning.
TWO_IMPORTS = ("rezono 0\npack sample\n\nschema sample\n  import \"linkml:types\"\n"
               "  import \"https://w3id.org/example/other\"\n\n" + ZONE)


class MissingHeaderHint(AssertionError):
    """The reader did not warn at a header line that writes its default, or changed the form."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingHeaderHint,
    reason="extra: decisions/language-readable-rules.md: In rezono/src/module-header.ts or module-metadata.ts, give "
           "W107 with the hint \"leave it out\" at `import \"linkml:types\"` when it is the only import, at "
           "`default range Text` and at `annotation layer = ...`, without changing the form. Add W107 to "
           "rezono/messages/en.json and nl.json if another test of that decision has not. Read section 3.",
)
def test_readable_header():
    short, full, two = read_modules(SHORT, FULL, TWO_IMPORTS)
    # The short header already reads with no member for the defaults; this does not change.
    assert not short["diagnostics"] and short["module"] is not None, short
    assert not {"imports", "defaultRange", "annotations", "iri"} & set(short["module"]), short["module"]
    problems = []
    want = [{"code": "W107", "span": at(FULL, text)}
            for text in ('import "linkml:types"', "default range Text", 'annotation layer = "facts"')]
    members = {"imports": ["linkml:types"], "defaultRange": "Text", "annotations": {"layer": "facts"}}
    if full["module"] is None or full["diagnostics"] != want:
        problems.append({"full": full["diagnostics"], "want": want})
    elif {key: full["module"].get(key) for key in members} != members:
        problems.append({"module": full["module"]})
    if two["module"] is None or two["diagnostics"]:
        problems.append({"two imports": two["diagnostics"]})
    if problems:
        raise MissingHeaderHint(json.dumps(problems, indent=2))
