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


@pytest.mark.xfail(
    strict=True,
    raises=MissingIntermediateInvariant,
    reason="extra: decisions/language-safe-steps.md: Read the rule option invariant intermediate within NAME as "
           "{invariant: intermediate, within: {relation: NAME}} in rezono/src/module-native-rule.ts, print it back, "
           "refuse it twice on one head and on a positional head with R000, give a module that uses it the format "
           "rezono.module/4 in rezono/src/module-json.ts, and admit the option in contracts/rezono-module.yaml. "
           "Read sections 3 and 4. test_step_declaration also adds rezono.module/4: whoever lands second resolves "
           "the conflict.",
)
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
