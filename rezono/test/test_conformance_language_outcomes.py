"""Every shared conformance case has exactly one outcome for the language.

An outcome is either a comparison that the language runs and passes, or an explicit
`unsupported.language` reason in the case file (tests/conformance/README.md). A case with
neither is skipped silently, and a case with both is ambiguous. Both are failures.
A reason that starts with PENDING marks a planned comparison: its case gives its language
spelling already, and the shared runner compares it, as a todo while the named task is an expected
failure. The task lifts its strict xfail and changes no case file; once the comparison passes, the
case has its outcome, and a planner may remove the reason. Until then the case has no outcome.
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
PENDING = "Waits for rezono/test/test_conformance_language_outcomes.py--"

# Cases that a dedicated language test owns instead of the shared runner, with that test. A dedicated
# test that is still an expected failure is its own task, so these cases are outside every gate below.
DEDICATED = {
    "expression-ask-partial-call": "rezono/test/test_expression_ask_partial_call.py",
    "expression-filtered-count": "rezono/test/test_expression_ts_filtered_count.py",
    "expression-negated-call": "rezono/test/test_expression_ts_negated_call.py",
    "value-ask-na-left-out": "compiler/tests/rezono/test_neutral_answer_cases.py",
    "value-value-invalid-blocks": "compiler/tests/rezono/test_neutral_answer_cases.py",
}

# Slot reads that the language answers with the spelling in their case file.
SLOT_READS = {
    "value-missing-optional", "value-missing-required", "value-negation-open", "value-reason-known-empty",
    "value-refused-float", "value-set-closed-empty", "value-set-open-empty", "value-two-values-single",
}

# Check statements and a question whose case gives its Rezono text under `check` or `ask` and its rows in the
# language's form. The shared runner compares them as follows, and nothing else in the expectation:
# - `check`: run check and publish from rezono/src/index.ts on the case's rows. `publication_blocked` is
#   outcome == "blocked"; `violations` is the ids of the violations; `undecided` lists subject (id), state and
#   reason of each undecided row, and `witness.undecided` its cause; `count_per_role` is the number of undecided
#   rows. For value-warn-never-blocks, each of the three entries is false when the warning publishes although
#   the rows hold a false, an unknown and an invalid outcome respectively. The top-level state and reason are
#   those of the one undecided row, or known and null without one.
# - `ask`: check the question and compare the answer schema's columns, in order: binder `ref Item`, then c1
#   `integer`, then c2 `ref Group`, from each slot's `ref` or `type`.
QUESTIONS_AND_CHECKS = {
    "value-check-invalid-overlap", "value-check-unknown", "value-projection-show", "value-require-unknown",
    "value-warn-never-blocks",
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
    out = []
    for case_id, case in selected.items():
        reason = (case.get("unsupported") or {}).get("language")
        stated = isinstance(reason, str) and bool(reason.strip()) and not reason.startswith(PENDING)
        if case_id in ran and stated:
            out.append(f"{case_id}: compared and also unsupported ({reason.strip()[:60]})")
        elif case_id not in ran and not stated:
            out.append(f"{case_id}: no language comparison and no unsupported.language reason")
    return out


def check(selected: dict[str, dict]) -> None:
    assert selected
    missing = problems(selected)
    if missing:
        raise MissingLanguageOutcome("; ".join(missing))


def expression_cases(cases: dict[str, dict]) -> dict[str, dict]:
    return {case_id: case for case_id, case in cases.items()
            if "expression" in case["input"] and case_id not in DEDICATED}


def test_dedicated_cases_name_their_test():
    cases = corpus()
    for case_id, test in DEDICATED.items():
        assert case_id in cases, case_id
        assert case_id in (ROOT / test).read_text("utf-8"), (case_id, test)


def test_language_compares_expression_cases():
    check(expression_cases(corpus()))


def test_language_compares_slot_read_cases():
    cases = corpus()
    check({case_id: cases[case_id] for case_id in SLOT_READS})


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageOutcome,
    reason="extra: rezono/test/shared-conformance.test.ts now compares the five QUESTIONS_AND_CHECKS cases as todo "
           "while this mark stands; verify they pass (fixing rezono/src/ if any fails) and lift this mark. Read "
           "tests/conformance/README.md.",
)
def test_language_compares_question_and_check_cases():
    cases = corpus()
    check({case_id: cases[case_id] for case_id in QUESTIONS_AND_CHECKS})


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageOutcome,
    reason="extra: Waits for a planner pull request, because only case files change and the evidence guard refuses "
           "lifting this mark beside them; give every remaining case exactly one language outcome. These cases "
           "concern hashes, wire snapshots, "
           "publication payloads and role worlds of other engines: record in each case file under "
           "tests/conformance/ the specific reason the language does not answer it, as unsupported.language. Change "
           "only those case files, not the runner or any expectation; if the language should answer a case, say so "
           "in this reason instead. Read tests/conformance/README.md.",
)
def test_language_accounts_for_remaining_cases():
    cases = corpus()
    named = set(expression_cases(cases)) | SLOT_READS | QUESTIONS_AND_CHECKS | set(DEDICATED)
    check({case_id: case for case_id, case in cases.items() if case_id not in named})
