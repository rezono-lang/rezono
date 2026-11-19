"""Every shared conformance case has exactly one outcome for the language.

An outcome is either a comparison that the language runs and passes, or an explicit
`unsupported.language` reason in the case file (tests/conformance/README.md). A case with
neither is skipped silently, and a case with both is ambiguous. Both are failures.
"""

from pathlib import Path
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "conformance"
PACKAGE = ROOT / "rezono"
RUNNER = "test/shared-conformance.test.ts"
PREFIX = "shared conformance: "

# Cases that a dedicated language test compares instead of the shared runner, with that test.
DEDICATED = {
    "expression-filtered-count": "rezono/test/test_expression_ts_filtered_count.py",
    "expression-negated-call": "rezono/test/test_expression_ts_negated_call.py",
}


class MissingLanguageOutcome(AssertionError):
    """A case has no language comparison and no unsupported reason, or has both."""


def corpus() -> dict[str, dict]:
    cases = {}
    for path in sorted(CORPUS.glob("*.yaml")):
        if path.name == "sources.yaml":
            continue
        case = yaml.safe_load(path.read_text("utf-8"))
        cases[case["id"]] = case
    return cases


def compared() -> set[str]:
    """The case ids the shared runner compared and passed, read from its TAP report."""
    result = subprocess.run(
        ["node", "--test", "--test-reporter=tap", RUNNER],
        cwd=PACKAGE, capture_output=True, encoding="utf-8",
    )
    passed = set()
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*ok \d+ - (.*?)(\s+#\s*(SKIP|TODO).*)?$", line)
        if match and not match.group(2) and match.group(1).startswith(PREFIX):
            passed.add(match.group(1)[len(PREFIX):])
    assert passed, f"the shared runner reported no passing case:\n{result.stdout[-2000:]}{result.stderr[-2000:]}"
    return passed


def problems(selected: dict[str, dict]) -> list[str]:
    ran = compared()
    for case_id, test in DEDICATED.items():
        text = (ROOT / test).read_text("utf-8")
        # The dedicated test names the case's probe and runs green; an expected failure is no comparison.
        if case_id in text and "xfail" not in text:
            ran.add(case_id)
    out = []
    for case_id, case in selected.items():
        reason = (case.get("unsupported") or {}).get("language")
        if case_id in ran and reason:
            out.append(f"{case_id}: compared and also unsupported ({reason.strip()[:60]})")
        elif case_id not in ran and not (isinstance(reason, str) and reason.strip()):
            out.append(f"{case_id}: no language comparison and no unsupported.language reason")
    return out


# The cases each task gives a language outcome. Every other case belongs to the remainder.
SLOT_READS = {
    "value-missing-optional", "value-missing-required", "value-negation-open", "value-reason-known-empty",
    "value-refused-float", "value-set-closed-empty", "value-set-open-empty", "value-two-values-single",
}
QUESTIONS_AND_CHECKS = {
    "value-ask-na-left-out", "value-check-invalid-overlap", "value-check-unknown", "value-projection-show",
    "value-require-unknown", "value-value-invalid-blocks", "value-warn-never-blocks",
    "value-withheld-derived-negation", "value-withheld-optional", "value-withheld-two-world",
}


def expression_cases(cases: dict[str, dict]) -> dict[str, dict]:
    return {case_id: case for case_id, case in cases.items() if "expression" in case["input"]}


def check(selected: dict[str, dict]) -> None:
    assert selected
    missing = problems(selected)
    if missing:
        raise MissingLanguageOutcome("; ".join(missing))


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageOutcome,
    reason="Compare every case whose input has `expression` in rezono/test/shared-conformance.test.ts, which "
           "selects only cases with `input.language` today: evaluate the expression with the case's rows, bindings, "
           "subject, world and dates through the language, and compare value, state and reason. Record "
           "unsupported.language only for a limitation you cannot remove, with its specific reason, for planner "
           "review. Read tests/conformance/README.md and decisions/language-expression-semantics.md section 1.",
)
def test_language_compares_expression_cases():
    check(expression_cases(corpus()))


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageOutcome,
    reason="Waits for rezono/test/test_conformance_language_outcomes.py--test_language_compares_expression_cases, "
           "which changes the same runner. Then compare the slot-read cases in SLOT_READS in "
           "rezono/test/shared-conformance.test.ts: read the case's slot of its subject under its world and "
           "cardinality and compare value, state and reason. value-set-open-empty follows "
           "decisions/conformance-value-set-open-empty.md. Read tests/conformance/README.md.",
)
def test_language_compares_slot_read_cases():
    cases = corpus()
    check({case_id: cases[case_id] for case_id in SLOT_READS})


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageOutcome,
    reason="Waits for rezono/test/test_conformance_language_outcomes.py--test_language_compares_slot_read_cases, "
           "which changes the same runner. Then compare the question and check cases in QUESTIONS_AND_CHECKS in "
           "rezono/test/shared-conformance.test.ts through the language's check and answer, including role "
           "filtering. Record unsupported.language only for a limitation you cannot remove, with its specific "
           "reason, for planner review. Read tests/conformance/README.md and decisions/question-predicate-outcomes.md.",
)
def test_language_compares_question_and_check_cases():
    cases = corpus()
    check({case_id: cases[case_id] for case_id in QUESTIONS_AND_CHECKS})


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageOutcome,
    reason="Give every remaining case exactly one language outcome. These cases concern hashes, wire snapshots, "
           "publication payloads and role worlds of other engines: record in each case file under "
           "tests/conformance/ the specific reason the language does not answer it, as unsupported.language. Change "
           "only those case files, not the runner or any expectation; if the language should answer a case, say so "
           "in this reason instead. Read tests/conformance/README.md.",
)
def test_language_accounts_for_remaining_cases():
    cases = corpus()
    named = set(expression_cases(cases)) | SLOT_READS | QUESTIONS_AND_CHECKS
    check({case_id: case for case_id, case in cases.items() if case_id not in named})
