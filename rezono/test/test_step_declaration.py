"""A module can declare a step: its match, scoped forbids, one typed effect and its confirmation
(decisions/language-safe-steps.md, section 2). The expected tree is copied from that decision."""

import json

import pytest

from reader_probe import read_modules

HEADER = "rezono 0\npack sample\n"
STEP = HEADER + """step install_policy(change: PolicyChange)
  when approved(change)
  forbid active_policy(change.target) within policy_inventory(change.zone)
  effect ruleset_install
    + ActivePolicy change.target {mode = change.mode, zone = change.zone}
  confirm policy_readback(change.zone) token change.confirmation
"""
DECLARED = {
    "step": "install_policy",
    "columns": [{"name": "change", "type": "PolicyChange"}],
    "when": {"call": ["approved", [{"path": ["change"]}]]},
    "forbid": [{
        "pattern": {"call": ["active_policy", [{"path": ["change", "target"]}]]},
        "within": {"call": ["policy_inventory", [{"path": ["change", "zone"]}]]},
    }],
    "effect": {
        "operation": "ruleset_install",
        "changes": [{"insert_row": {
            "kind": "ActivePolicy",
            "key": {"path": ["change", "target"]},
            "slots": [{"name": "mode", "value": {"path": ["change", "mode"]}},
                      {"name": "zone", "value": {"path": ["change", "zone"]}}],
        }}],
    },
    "confirm": {
        "reader": {"call": ["policy_readback", [{"path": ["change", "zone"]}]]},
        "token": {"path": ["change", "confirmation"]},
    },
}


class MissingStepDeclaration(AssertionError):
    """The module reader did not read, print or place a step as the decision gives it."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingStepDeclaration,
    reason="extra: decisions/language-safe-steps.md: Read a step declaration (typed columns, one when, zero or more "
           "forbid ... within ..., one effect with its changes, one confirm ... token ...) in a new "
           "rezono/src/module-step.ts registered in rezono/src/module.ts, print it back in that order with two "
           "spaces per level, give a module with a step the format rezono.module/4 in rezono/src/module-json.ts, "
           "and admit the closed shape in contracts/rezono-module.yaml. Read sections 2 and 4. "
           "test_invariant_intermediate also adds rezono.module/4: whoever lands second resolves the conflict.",
)
def test_step_declaration():
    without_forbid = STEP.replace(
        "  forbid active_policy(change.target) within policy_inventory(change.zone)\n", "")
    without_confirm = STEP.replace("  confirm policy_readback(change.zone) token change.confirmation\n", "")
    plain = HEADER + "kind Zone world closed\n  name: Text\n"
    step, bare, unconfirmed, kept = read_modules(STEP, without_forbid, without_confirm, plain)
    # Counter-cases: a step has one confirm, and a module without a step keeps the format it already had.
    assert unconfirmed["module"] is None and unconfirmed["diagnostics"], unconfirmed
    assert kept["format"] == "rezono.module/1" and not kept["diagnostics"], kept
    unforbidden = {key: value for key, value in DECLARED.items() if key != "forbid"}
    for read, source, decl in ((step, STEP, DECLARED), (bare, without_forbid, unforbidden)):
        if (read["diagnostics"] or read["format"] != "rezono.module/4" or read["module"]["decls"] != [decl]
                or read["printed"] != source):
            raise MissingStepDeclaration(json.dumps(read, indent=2))
