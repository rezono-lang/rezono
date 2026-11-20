"""A typed rule head can mark its invariant for intermediate states: `invariant intermediate within <coverage>`
(decisions/language-safe-steps.md, section 3). The expected option is copied from that decision."""

import json

import pytest

from reader_probe import read_modules

HEADER = "rezono 0\npack sample\n"
GUARD = "when exposed(endpoint) and lacks_policy(endpoint)\n"
INTERMEDIATE = (HEADER + "rule missing_policy(endpoint: Endpoint) invariant intermediate within policy_coverage "
                + GUARD)
RULE = {
    "rule": "missing_policy",
    "columns": [{"name": "endpoint", "type": "Endpoint"}],
    "options": [{"invariant": "intermediate", "within": {"relation": "policy_coverage"}}],
    "when": {"and": [{"call": ["exposed", [{"path": ["endpoint"]}]]},
                     {"call": ["lacks_policy", [{"path": ["endpoint"]}]]}]},
}


class MissingIntermediateInvariant(AssertionError):
    """The module reader did not read, print or refuse an intermediate invariant as the decision gives it."""


def test_invariant_intermediate():
    bare = HEADER + "rule missing_policy(endpoint: Endpoint) invariant " + GUARD
    twice = INTERMEDIATE.replace(" when", " invariant intermediate within policy_coverage when")
    positional = HEADER + "rule missing_policy(endpoint) invariant intermediate within policy_coverage " + GUARD
    read, plain, repeated, untyped = read_modules(INTERMEDIATE, bare, twice, positional)
    # Counter-case: a bare invariant keeps its option and its format, before and after.
    assert plain["format"] == "rezono.module/3" and plain["module"]["decls"][0]["options"] == [{"invariant": True}], plain
    problems = []
    if (read["diagnostics"] or read["format"] != "rezono.module/4" or read["module"]["decls"] != [RULE]
            or read["printed"] != INTERMEDIATE):
        problems.append(read)
    for refused in (repeated, untyped):
        if refused["module"] is not None or "R000" not in [d["code"] for d in refused["diagnostics"]]:
            problems.append(refused)
    if problems:
        raise MissingIntermediateInvariant(json.dumps(problems, indent=2))
