"""A state literal that names a reason by a label no reason declares is R029 at that label
(decisions/language-reasons.md, section Reading a label; docs/rezono/v0.md section 10)."""

import json

import pytest

from reader_probe import at, read_modules

HEADER = "rezono 0\npack sample\n"
BODY = """reason no_rate = "no monthly rate published yet"
kind Host world closed
  rate: Int
fact Host
  | id     | rate |
  | host-a | {cell} |
"""


def source(cell: str) -> str:
    return HEADER + BODY.replace("{cell}", cell)


class MissingReasonLabelCheck(AssertionError):
    """The reader did not refuse a label that no reason declares with R029 at that label."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReasonLabelCheck,
    reason="extra: decisions/language-reasons.md: Refuse a state literal whose quoted label is the label of no "
           "reason declaration of the module with R029 at the label, in rezono/src/module-check.ts, and give R029 "
           "its sentence in each language of rezono/messages/. Read the section Reading a label. Waits for a "
           "planner to declare reason not_measured in the fact-row case of the test 'the four states of a value' in "
           "rezono/test/module-json.test.ts, which reads unknown \"not measured yet\" undeclared and expects a form.",
)
def test_reason_label():
    stray = source('unknown "no rate yet"')
    declared, coded, refused = read_modules(source('unknown "no monthly rate published yet"'),
                                            source("unknown no_rate"), stray)
    # Counter-cases, before and after: a declared label and a code are read without a diagnostic.
    for read in (declared, coded):
        assert read["module"] is not None and not read["diagnostics"], read
    if refused["module"] is not None or refused["diagnostics"] != [{"code": "R029",
                                                                    "span": at(stray, '"no rate yet"')}]:
        raise MissingReasonLabelCheck(json.dumps(refused, indent=2))
