"""R021: a version that replaces a version the declaration does not have, or replacements that form a cycle."""

import json
from pathlib import Path

import pytest

from reader_probe import at, read_modules

HEADER = "rezono 0\npack sample\n"
VALID = (HEADER + "param quota: Int\n"
         "  version 1, valid 2026-01-01.., known 2025-09-16 = 5\n"
         "  version 2 replaces 1, valid 2026-01-01.., known 2025-09-16 = 6\n")


class MissingReplacedVersionCheck(AssertionError):
    """The reader accepted a replacement of a missing version or a cycle, or refused it differently."""


class MissingR021Sentence(AssertionError):
    """A message catalogue has no sentence for R021 with its three arguments."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReplacedVersionCheck,
    reason="extra: decisions/language-parameters.md: In rezono/src/module-version.ts, refuse with R021 a number after "
           "replaces that names no version of the same declaration, at that number, and replaces lines that form a "
           "cycle, at the number after replaces of the first version of the cycle, with no module, as R018 is "
           "refused. Read section R021. The sentence is "
           "test_r021_has_a_sentence.",
)
def test_reader_refuses_a_missing_or_cyclic_replacement():
    unknown = VALID.replace("replaces 1", "replaces 4")
    cycle = VALID.replace("version 1,", "version 1 replaces 2,")
    itself = VALID.replace("replaces 1", "replaces 2")
    expected = [
        # The control: a replacement of a version that exists reads, with the replaced number as text.
        ("valid", None),
        ("unknown", at(unknown, "4", "replaces ")),
        # Versions 1 and 2 replace each other; version 1 comes first, so R021 is at the number it replaces.
        ("cycle", at(cycle, "2", "version 1 replaces ")),
        ("itself", at(itself, "2", "version 2 replaces ")),
    ]
    differences = []
    for (name, span), read in zip(expected, read_modules(VALID, unknown, cycle, itself), strict=True):
        if span is None:
            versions = (read["module"] or {}).get("decls", [{}])[0].get("versions", [])
            if read["diagnostics"] or [version.get("replaces") for version in versions] != [None, "1"]:
                differences.append({"case": name, "read": read})
        elif read["module"] is not None or read["diagnostics"] != [{"code": "R021", "span": span}]:
            differences.append({"case": name, "read": read, "expected": [{"code": "R021", "span": span}]})
    if differences:
        raise MissingReplacedVersionCheck(json.dumps(differences, indent=2))


@pytest.mark.xfail(
    strict=True,
    raises=MissingR021Sentence,
    reason="extra: decisions/language-parameters.md: Add the sentence of R021 to rezono/messages/en.json and "
           "rezono/messages/nl.json, with the replacing version as {0}, the number it names as {1} and the "
           "declaration as {2}, covering both a missing version and a cycle. Read section R021.",
)
def test_r021_has_a_sentence():
    messages = Path(__file__).parents[1] / "messages"
    missing = []
    for language in ("en", "nl"):
        sentence = json.loads((messages / f"{language}.json").read_text(encoding="utf-8")).get("R021", "")
        if not all(f"{{{index}}}" in sentence for index in range(3)):
            missing.append(language)
    if missing:
        raise MissingR021Sentence(f"no R021 sentence with {{0}}, {{1}} and {{2}} in {', '.join(missing)}")
