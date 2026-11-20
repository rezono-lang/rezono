"""A rule clause carries its sentence with `means` and its source with `@` (decisions/language-readable-rules.md,
section 2). The members are written from that decision; the sources are in the printer's form, with one space
before `@` as for an exception line."""

import json

import pytest
from reader_probe import read_modules

HEADER = "rezono 0\npack sample\nkind Item world closed\n"
RULE = "rule listed(item: Item) when item in Item"
BOTH = HEADER + RULE + '\n  means "{$item} is listed." @ policy#art-3\n'
SOURCE_ONLY = HEADER + RULE + " @ policy#art-3\n"
SENTENCE_ONLY = HEADER + RULE + '\n  means "{$item} is listed."\n'


class MissingRuleSentence(AssertionError):
    """The reader did not read, print or refuse a rule's sentence and source as the decision gives them."""


def test_rule_sentence():
    plain, both, source_only, sentence_only, *refused = read_modules(
        HEADER + RULE + "\n",
        BOTH,
        SOURCE_ONLY,
        SENTENCE_ONLY,
        HEADER + RULE + "\n  means\n",  # no text
        HEADER + RULE + '\n  means "a"\n  means "b"\n',  # twice
        HEADER + RULE + '  @ policy#art-3\n  means "a"  @ policy#art-4\n',  # two sources
    )
    # Counter-case: without the line the rule keeps its members.
    [base] = [d for d in plain["module"]["decls"] if d.get("rule") == "listed"]
    assert "means" not in base and "source" not in base, base
    problems = []
    expected = (
        (both, BOTH, {"means": "{$item} is listed.", "source": "policy#art-3"}),
        (source_only, SOURCE_ONLY, {"source": "policy#art-3"}),
        (sentence_only, SENTENCE_ONLY, {"means": "{$item} is listed."}),
    )
    for read, source, members in expected:
        rules = [d for d in (read["module"] or {}).get("decls", []) if d.get("rule") == "listed"]
        if read["diagnostics"] or rules != [base | members] or read["printed"] != source:
            problems.append({"source": source, "read": read})
    for refusal in refused:
        if refusal["module"] is not None or "R000" not in [d["code"] for d in refusal["diagnostics"]]:
            problems.append(refusal)
    if problems:
        raise MissingRuleSentence(json.dumps(problems, indent=2))
