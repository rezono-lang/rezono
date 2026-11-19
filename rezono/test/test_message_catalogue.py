"""Every R or W code the compiler or the language reader reports has a sentence in each language of the catalogue.

contracts/diagnostic.yaml: the code names the diagnostic, and a reader's sentence for it comes from the message
files. The codes are read from the sources, not from a list kept by hand, so a new code without a sentence fails.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "compiler/rezono_compiler": "*.py",
    "rezono/src": "*.ts",
}
CATALOGUE = ROOT / "rezono" / "messages"
# A code as a quoted literal, the way a diagnostic or a refusal is given one; a code named in a comment is not.
CODE = re.compile(r"""(["'`])([RW]\d{3})\1""")


def reported(folder: str, pattern: str) -> set[str]:
    """The R and W codes that the sources under one folder give a diagnostic."""
    return {match.group(2)
            for path in sorted((ROOT / folder).rglob(pattern))
            for match in CODE.finditer(path.read_text(encoding="utf-8"))}


def catalogue() -> dict[str, dict[str, str]]:
    """Each language of the catalogue with its sentences by code."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(CATALOGUE.glob("*.json"))}


def missing(codes: set[str], languages: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    """Per language, the codes it has no sentence for."""
    gaps = {language: sorted(code for code in codes if not sentences.get(code))
            for language, sentences in languages.items()}
    return {language: codes for language, codes in gaps.items() if codes}


def test_the_codes_are_read_from_both_sources_and_a_gap_is_found():
    compiler = reported("compiler/rezono_compiler", "*.py")
    reader = reported("rezono/src", "*.ts")
    # Each source reports codes of its own, so an empty scan cannot pass for a complete catalogue.
    assert {"R046", "R049"} <= compiler
    assert {"R000", "R015", "W105"} <= reader
    languages = catalogue()
    assert {"en", "nl"} <= set(languages)
    # Counter-case: a code that no language has is found missing in every language; an empty sentence counts as none.
    assert missing({"R999"}, languages) == {language: ["R999"] for language in languages}
    assert missing({"R000"}, {"en": {"R000": "x"}, "nl": {"R000": ""}}) == {"nl": ["R000"]}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: contracts/diagnostic.yaml: Add a sentence for R046 and R048 to rezono/messages/en.json and "
    "rezono/messages/nl.json, in both languages, with the same arguments in each, so that every R or W code "
    "that compiler/rezono_compiler or rezono/src reports has a sentence in each language of the catalogue. "
    "R046 is a native rule name outside the verified imports or the public interface of its module, and "
    "R048 a native rule signature or option that does not fit its owning head or has no defining clause "
    "(compiler/rezono_compiler/native_rule_signatures.py and native_rule_dl.py; "
    "docs/rezono/native-rule-pack-link.md)."))
def test_every_reported_code_has_a_sentence_in_each_language():
    codes = set().union(*(reported(folder, pattern) for folder, pattern in SOURCES.items()))
    assert missing(codes, catalogue()) == {}
