"""The engine epoch as a std-loop run: why an epoch is published, and why not (decisions/loop-engine-epoch.md).

The scenario is written by hand from sections 3 to 6 of the decision: one run of epoch 7 of a pack with the two
filtered roles guest and auditor, every gate step observed done, every required check green, and one recorded
write-forms plan. Each refusal case changes one observation and names the record the refusal must cite.
"""
import copy
import json
import re
from pathlib import Path

import pytest
import yaml

from pack_records import evaluate

ROOT = Path(__file__).resolve().parents[2]
EPOCH = ROOT / "epoch"
PIN = EPOCH / "engine-pin.yaml"
RUN = "epoch-7"
ROLES = ("guest", "auditor")
GATES = ("compile", "evaluate-duckdb", "evaluate-feldera", "compare-engines", "check")
TOKENS = {"compile": "compiled", "evaluate-duckdb": "evaluated-duckdb", "evaluate-feldera": "evaluated-feldera",
          "compare-engines": "engines-agree", "check": "checked", "write-forms": "forms-written",
          **{f"sign-{role}": f"signed-{role}" for role in ROLES},
          **{f"distribute-{role}": f"distributed-{role}" for role in ROLES}}
TOOLS = {"compile": "compiler", "evaluate-duckdb": "duckdb", "evaluate-feldera": "feldera",
         "compare-engines": "comparison", "check": "checker"}
WRITE_PLAN = "5" * 64
COMPLETE_ONLY = {"pack-facts", "source-facts", "detail-proofs"}


class MissingEpochPack(AssertionError):
    """The engine epoch pack (epoch/) does not exist yet."""


class MissingEnginePin(AssertionError):
    """No released engine is pinned to evaluate the engine epoch run."""


def hexes(digit, length=64):
    return digit * length


def scenario():
    steps = [
        {"id": "compile", "precedes": ["evaluate-duckdb", "evaluate-feldera"]},
        {"id": "evaluate-duckdb", "precedes": ["compare-engines"]},
        {"id": "evaluate-feldera", "precedes": ["compare-engines"]},
        {"id": "compare-engines", "precedes": ["check"]},
        {"id": "check", "precedes": ["write-forms"]},
        {"id": "write-forms", "precedes": [f"sign-{role}" for role in ROLES]},
        *({"id": f"sign-{role}", "precedes": [f"distribute-{role}"]} for role in ROLES),
        *({"id": f"distribute-{role}"} for role in ROLES),
    ]
    return {
        "loop_active_run": [{"id": RUN}],
        "loop_step": steps,
        "loop_completion": [{"id": f"def-{step}", "run": RUN, "step": step, "token": token, "reason": f"def-{step}"}
                            for step, token in TOKENS.items()],
        "loop_expectation": [{"id": token, "value": "yes"} for token in TOKENS.values()],
        # A gate observation's reason names the run and the step, never a digest over rows (section 3.5).
        "loop_observation": [{"id": f"obs-{step}", "run": RUN, "token": TOKENS[step], "event_time": index + 1,
                              "state": "known", "value": "yes", "reason": f"{RUN} {step}"}
                             for index, step in enumerate(GATES)],
        "loop_effect_plan": [{"id": WRITE_PLAN, "run": RUN, "step": "write-forms", "reason": "manifest"}],
        "epoch_run": [{"id": RUN, "pack": "toy", "epoch": 7, "commit": hexes("a", 40), "profile": hexes("b")}],
        "epoch_role": [{"id": f"role-{role}", "run": RUN, "name": role} for role in ROLES],
        "epoch_role_step": [{"id": f"{stage}-step-{role}", "run": RUN, "step": f"{stage}-{role}",
                             "role": f"role-{role}", "stage": stage}
                            for role in ROLES for stage in ("sign", "distribute")],
        "epoch_engine_pin": [{"id": "engine-pin", "run": RUN, "version": "0.1.0", "wheel_sha256": hexes("c"),
                              "commit": hexes("d", 40)}],
        "epoch_tool": [{"id": f"tool-{step}", "run": RUN, "step": step, "tool": tool, "version": "0.2.0",
                        "sha256": hexes("e")} for step, tool in TOOLS.items()],
        "epoch_definition": [{"id": "definition", "run": RUN, "definition_sha256": hexes("f"),
                              "compiler_sha256": hexes("0")}],
        # A stable pack (1.2.0) with a minor change and a new minor version: the surface gate passes.
        "epoch_surface": [{"id": "surface", "run": RUN, "against": "m-6", "class": "minor", "before_major": 1,
                           "before_minor": 2, "before_patch": 0, "after_major": 1, "after_minor": 3,
                           "after_patch": 0}],
        "epoch_check": [
            {"id": "check-engines", "run": RUN, "step": "compare-engines", "check": "rezono:engines",
             "outcome": "green", "violations": 0, "source": "comparison"},
            {"id": "check-proofs", "run": RUN, "step": "check", "check": "rezono:proofs", "outcome": "green",
             "violations": 0, "source": "checker"},
        ],
        "epoch_role_check": [{"id": f"check-{check}-{role}", "run": RUN, "step": "check", "role": f"role-{role}",
                              "check": f"rezono:{check}", "outcome": "green", "violations": 0, "source": "checker"}
                             for role in ROLES for check in ("proofs", "access")],
        "epoch_required_check": [
            {"id": "required-engines", "step": "compare-engines", "check": "rezono:engines", "scope": "run"},
            {"id": "required-proofs", "step": "check", "check": "rezono:proofs", "scope": "run"},
            {"id": "required-role-proofs", "step": "check", "check": "rezono:proofs", "scope": "role"},
            {"id": "required-role-access", "step": "check", "check": "rezono:access", "scope": "role"},
        ],
        "epoch_role_form": [{"id": f"form-{role}", "run": RUN, "role": f"role-{role}", "snapshots_sha256": hexes("3"),
                             "sources_sha256": hexes("4"), "objects_sha256": hexes("6")} for role in ROLES],
        # Complete only (section 3.5): never a premise of a role's publish_allowed.
        "epoch_pack_facts": [{"id": "pack-facts", "run": RUN, "pack_sha256": hexes("9")}],
        "epoch_source": [{"id": "source-facts", "run": RUN, "source": "facts", "position": hexes("7", 40)}],
        "epoch_check_detail": [{"id": "detail-proofs", "check": "check-proofs", "report_sha256": hexes("8")}],
    }


def model():
    if not (EPOCH / "pack.yaml").is_file():
        raise MissingEpochPack("epoch/pack.yaml does not exist")
    from rezono_compiler import pack

    return pack.read(EPOCH)


def ground_ids(program, explainer, relation, row):
    """The record ids of the base rows a row's chosen proof cites as positive premises, at any depth."""
    proof = explainer.proof(relation, row, "fixture")
    ids = set()
    for witness in proof["witnesses"]:
        for premise in witness["premises"]:
            if premise["polarity"] == "positive" and premise["row"]["relation"] in program.base_used():
                key = json.loads(premise["row"]["key"])
                if key:
                    ids.add(key[0])
    return ids


def allowed(rows):
    return {row[:3] for row in rows.get("publish_allowed", set())}


def planned(rows, step):
    return {row[:3] for row in rows.get("effect_planned", set()) if row[1] == step}


def test_publish_allowed_cites_every_gate_and_pin():
    epoch = model()
    program, rows, explainer = evaluate(epoch, scenario())
    assert allowed(rows) == {(RUN, "7", role) for role in ROLES}
    assert {row[3] for row in rows["publish_allowed"] if row[2] == "guest"} == {"form-guest"}
    guest, = (row for row in rows["publish_allowed"] if row[2] == "guest")
    cited = ground_ids(program, explainer, "publish_allowed", guest)
    expected = {*(f"obs-{step}" for step in GATES), *(f"tool-{step}" for step in GATES), "engine-pin", "definition",
                "form-guest", "check-proofs-guest", "check-access-guest"}
    assert expected <= cited, sorted(expected - cited)
    other_role = {"form-auditor", "check-proofs-auditor", "check-access-auditor"}
    assert not cited & (COMPLETE_ONLY | other_role), sorted(cited & (COMPLETE_ONLY | other_role))
    assert planned(rows, "write-forms") == {(RUN, "write-forms", WRITE_PLAN)}
    # Without the Feldera evaluation no gate opens: nothing is allowed and nothing is written.
    missing = scenario()
    missing["loop_observation"] = [o for o in missing["loop_observation"] if o["id"] != "obs-evaluate-feldera"]
    _, rows, _ = evaluate(epoch, missing)
    assert allowed(rows) == set()
    assert planned(rows, "write-forms") == set()


def red_run_check(data):
    data["epoch_check"][1].update(outcome="red", violations=2)


def unknown_run_check(data):
    data["epoch_check"].append({"id": "check-engine-own", "run": RUN, "step": "evaluate-duckdb",
                                "check": "rezono:invariants", "outcome": "unknown", "violations": 0,
                                "source": "duckdb"})


def green_with_violations(data):
    data["epoch_check"][1]["violations"] = 1


def engines_disagree(data):
    data["epoch_check"][0].update(outcome="red", violations=3)


def red_role_check(data):
    for check in data["epoch_role_check"]:
        if check["id"] == "check-access-auditor":
            check.update(outcome="red", violations=1)


def required_conclusion_missing(data):
    data["epoch_role_check"].append({"id": "check-required-guest", "run": RUN, "step": "check",
                                     "role": "role-guest", "check": "publication_required", "outcome": "red",
                                     "violations": 1, "source": "checker"})


def missing_required(data):
    data["epoch_role_check"] = [c for c in data["epoch_role_check"] if c["id"] != "check-proofs-auditor"]


def surface_major(data):
    data["epoch_surface"][0].update({"class": "major", "after_major": 2, "after_minor": 0})


def surface_too_small(data):
    data["epoch_surface"][0].update(after_minor=2, after_patch=1)


def surface_unstable(data):
    data["epoch_surface"][0].update({"class": "major", "before_major": 0, "after_major": 0, "after_minor": 3})


# Worked by hand from the fate table of decisions/loop-engine-epoch.md section 3.4: each change to a gate verdict
# of fate (c) and the record the refusal of write-forms must cite.
REFUSALS = [
    (red_run_check, "check-proofs"),
    (unknown_run_check, "check-engine-own"),
    (green_with_violations, "check-proofs"),
    (engines_disagree, "check-engines"),
    (red_role_check, "check-access-auditor"),
    (required_conclusion_missing, "check-required-guest"),
    (missing_required, "required-role-proofs"),
    (surface_major, "surface"),
    (surface_too_small, "surface"),
]


def test_publication_gates_are_derived_refusals():
    epoch = model()
    _, rows, _ = evaluate(epoch, scenario())
    assert not any(row[:2] == (RUN, "write-forms") for row in rows.get("stuck", set()))
    for change, culprit in REFUSALS:
        data = copy.deepcopy(scenario())
        change(data)
        program, rows, explainer = evaluate(epoch, data)
        refused = [row for row in rows.get("stuck", set()) if row[:2] == (RUN, "write-forms")]
        assert refused, change.__name__
        assert any(culprit in ground_ids(program, explainer, "stuck", row) for row in refused), change.__name__
        assert allowed(rows) == set(), change.__name__
        assert planned(rows, "write-forms") == set(), change.__name__
    # A major change of a pack still at 0.y.z refuses nothing (decisions/language-surface-compatibility.md).
    data = copy.deepcopy(scenario())
    surface_unstable(data)
    _, rows, _ = evaluate(epoch, data)
    assert not any(row[:2] == (RUN, "write-forms") for row in rows.get("stuck", set()))
    assert allowed(rows) == {(RUN, "7", role) for role in ROLES}
    # Fate (d): the check step's adapter recorded the raise of an input-integrity check instead of its completion.
    data = copy.deepcopy(scenario())
    data["loop_observation"] = [o for o in data["loop_observation"] if o["id"] != "obs-check"]
    data["loop_refusal"] = [{"id": "refused-assets", "run": RUN, "step": "check", "reason": "rezono:assets"}]
    program, rows, explainer = evaluate(epoch, data)
    refused = [row for row in rows.get("stuck", set()) if row[:2] == (RUN, "check")]
    assert any("refused-assets" in ground_ids(program, explainer, "stuck", row) for row in refused), refused
    assert allowed(rows) == set()
    assert planned(rows, "write-forms") == set()


def hidden_world(data):
    """The same run in a world that differs only in rows no filtered role reads (section 3.5)."""
    data["epoch_pack_facts"][0]["pack_sha256"] = hexes("a")
    data["epoch_source"][0]["position"] = hexes("b", 40)
    data["epoch_check_detail"][0].update(first="row 3 has no witness", report_sha256=hexes("c"))
    return data


def test_a_role_witness_ignores_complete_only_rows():
    epoch = model()
    proofs, complete = [], []
    for data in (scenario(), hidden_world(scenario())):
        program, rows, explainer = evaluate(epoch, data)
        proofs.append({row[2]: json.dumps(explainer.proof("publish_allowed", row, "fixture"), sort_keys=True)
                       for row in rows["publish_allowed"]})
        whole = [row for row in rows.get("epoch_allowed", set()) if row[:2] == (RUN, "7")]
        assert whole, rows.get("epoch_allowed")
        complete.append(set().union(*(ground_ids(program, explainer, "epoch_allowed", row) for row in whole)))
    assert set(proofs[0]) == set(ROLES)
    assert proofs[0] == proofs[1]
    assert {"pack-facts", "source-facts"} <= complete[0] and {"pack-facts", "source-facts"} <= complete[1]


def version(text):
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", text)
    assert match, f"{text!r} is not a release version"
    return tuple(int(part) for part in match.groups())


@pytest.mark.xfail(
    strict=True,
    raises=MissingEnginePin,
    reason=(
        "extra: decisions/loop-engine-epoch.md: section 6. Waits for the first release of the rezono wheel. Then "
        "epoch/engine-pin.yaml names the released engine that evaluates the engine epoch run: version, the "
        "wheel_sha256 of the released wheel and the 40-hex commit of its v<version> tag, with a version lower than "
        "the version in rezono/package.json, so the engine that judges a commit is never that commit's engine."
    ),
)
def test_the_loop_engine_is_an_earlier_release():
    if not PIN.is_file():
        raise MissingEnginePin("epoch/engine-pin.yaml does not exist")
    pin = yaml.safe_load(PIN.read_text(encoding="utf-8"))
    assert set(pin) == {"version", "wheel_sha256", "commit"}, sorted(pin)
    assert re.fullmatch(r"[0-9a-f]{64}", pin["wheel_sha256"]), pin["wheel_sha256"]
    assert re.fullmatch(r"[0-9a-f]{40}", pin["commit"]), pin["commit"]
    own = json.loads((ROOT / "rezono" / "package.json").read_text(encoding="utf-8"))["version"]
    assert version(pin["version"]) < version(own), (pin["version"], own)
