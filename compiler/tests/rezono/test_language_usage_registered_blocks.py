"""The usage inventory counts a step, an intermediate invariant and a deprecated declaration as building blocks of
their own, each with its reader and lowering tests (decisions/language-safe-steps.md, section 4, and
decisions/language-deprecation.md), instead of as unclassified syntax."""

import pytest

from language_usage import EVIDENCE, render


class MissingRegisteredBlock(AssertionError):
    """The inventory did not list a decided building block with its own row and evidence."""


MODULE = """rezono 0
pack sample

deprecated "use ProviderZone" until 2027-07-01
kind Zone world closed
  name: Text

rule missing_policy(endpoint: Endpoint) invariant intermediate within policy_coverage when exposed(endpoint)

step install_policy(change: PolicyChange)
  when approved(change)
  effect ruleset_install
    + ActivePolicy change.target {mode = change.mode}
  confirm policy_readback(change.zone) token change.confirmation
"""

EXPECTED = [
    "| deprecated-declaration | 1 | Pending ([reader](../../rezono/test/test_deprecated_declaration.py), "
    "[lowering](../../compiler/tests/rezono/test_lower_deprecated.py)) |",
    "| intermediate-invariant | 1 | Pending ([reader](../../rezono/test/test_invariant_intermediate.py), "
    "[lowering](../../compiler/tests/rezono/test_lower_intermediate_invariant.py)) |",
    "| step-declaration | 1 | Pending ([reader](../../rezono/test/test_step_declaration.py), "
    "[lowering](../../compiler/tests/rezono/test_lower_step_declaration.py)) |",
]


def test_language_usage_registered_blocks(tmp_path):
    (tmp_path / "packs/sample/rezono").mkdir(parents=True)
    (tmp_path / "packs/sample/pack.yaml").write_text("name: sample\n", encoding="utf-8")
    (tmp_path / "packs/sample/rezono/safety.rezono").write_text(MODULE, encoding="utf-8")
    output = render(tmp_path)
    # Counter-case: the kind and the rule keep their own rows.
    assert "| kind | 1 |" in output, output
    rows = [line for line in output.splitlines()
            if line.startswith(("| deprecated-declaration |", "| intermediate-invariant |", "| step-declaration |"))]
    if sorted(rows) != EXPECTED or "unclassified-authored-syntax" in output:
        raise MissingRegisteredBlock(output)


def test_safe_step_blocks_require_lowering_evidence():
    assert ("compiler/tests/rezono/test_lower_intermediate_invariant.py", "test_lower_intermediate_invariant") in (
        EVIDENCE["intermediate-invariant"]
    )
    assert ("compiler/tests/rezono/test_lower_step_declaration.py", "test_lower_step_declaration") in (
        EVIDENCE["step-declaration"]
    )
