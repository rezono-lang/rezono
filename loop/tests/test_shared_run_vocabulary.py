"""One run vocabulary in std-loop: claims, effects and derived refusals have one home (decisions/loop-engine-epoch.md).

The expectations are worked by hand from sections 2 and 5 of the decision and from the formal Effect and Claims
models: an attempt consumes its plan's key, the first readback after an effective attempt settles it, and a
refusal that an importing pack derives makes the refused step stuck with that pack's witness.
"""
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from pack_records import LOOP, ORDER, evaluate

ROOT = Path(__file__).resolve().parents[2]
EFFECT = ROOT / "contracts" / "effect.yaml"
RUN = "current"

SHARED = {
    "LoopEffectPlan": {"id", "run", "step", "reason"},
    "LoopEffectAttempt": {"id", "run", "plan", "sent_at", "outcome", "source"},
    "LoopEffectReadback": {"id", "run", "plan", "observed_at", "state", "receipt", "source"},
    "LoopClaim": {"id", "run", "subject", "generation", "observed_at", "source"},
    "LoopClaimRenewal": {"id", "claim", "generation", "at", "source"},
}
MOVED_KINDS = ("BuildClaimActivity", "BuildClaimDelete", "BuildClaimRefRead")
MOVED_RULES = ("build_claim_latest_push", "build_claim_push_tie", "build_claim_lease_start", "build_claim_lease_ended",
               "build_claim_settling_read", "build_claim_settled_earlier", "build_claim_first_settling")
KEPT_RULES = ("build_claim_release_plan", "build_claim_held", "build_claim_released", "build_claim_release_discarded",
              "build_claim_release_pending")
SHARED_RULES = ("claim_lease_ended", "claim_held", "effect_planned", "effect_attempted", "effect_pending",
                "effect_confirmed", "effect_discarded", "effect_state")


class MissingSharedKind(AssertionError):
    """std-loop does not declare a claim or effect kind that the build, provider and engine epoch runs share."""


class SecondDefinition(AssertionError):
    """A run concept that std-loop owns is still defined in another pack."""


class MissingExtension(AssertionError):
    """std-loop does not declare the extensible relation an importing pack derives."""


def schema_documents(folder):
    return [yaml.safe_load(path.read_text(encoding="utf-8")) or {} for path in sorted(folder.glob("*.yaml"))]


def classes(folder):
    return {name: body or {} for doc in schema_documents(folder) for name, body in (doc.get("classes") or {}).items()}


def enums(folder):
    return {name: body or {} for doc in schema_documents(folder) for name, body in (doc.get("enums") or {}).items()}


def declared(folder):
    """The relation names the .dl files of a rules folder declare."""
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.dl")))
    return set(re.findall(r"^\s*\.decl\s+(\w+)\s*\(", text, re.MULTILINE))


def extensible(folder, name):
    """Whether a .dl file of the folder declares `name` with the `// @extend` option on the line before."""
    pattern = re.compile(r"//\s*@extend\s*\n\s*\.decl\s+" + re.escape(name) + r"\s*\(")
    return any(pattern.search(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.dl")))


def effect_states():
    return set(yaml.safe_load(EFFECT.read_text(encoding="utf-8"))["enums"]["EffectState"]["permissible_values"])


def _std_loop_model():
    from rezono_compiler import pack

    return pack.read(LOOP)


def _std_loop_extensible(name):
    from rezono_compiler import rules as ir

    rel = ir.load(_std_loop_model().rules).relations.get(name)
    return bool(rel and rel.extend)


def test_effects_and_claims_are_declared_once():
    model = _std_loop_model()
    by_class = {}
    for kind in model.kinds.values():
        slots = set(kind.slots)
        if kind.identifier:
            slots.add(kind.identifier)
        by_class[kind.cls] = slots
    missing = sorted(set(SHARED) - set(by_class))
    if missing:
        raise MissingSharedKind(f"packs/std-loop lacks {missing}")
    for name, slots in SHARED.items():
        assert slots <= by_class[name], (name, sorted(slots - by_class[name]))
    states = effect_states()
    assert "loop_effect_state" in model.enums, "packs/std-loop lacks the enum LoopEffectState"
    assert set(model.enums["loop_effect_state"]) == states
    folders = [ROOT / "build" / "schema", ROOT / "epoch" / "schema",
               *sorted(path / "schema" for path in (ROOT / "run" / "packs").iterdir() if path.is_dir())]
    copies = [f"{folder.relative_to(ROOT)}: {name}" for folder in folders if folder.is_dir()
              for name, body in enums(folder).items() if set(body.get("permissible_values") or {}) == states]
    assert not copies, f"the effect states are declared again in {copies}"


@pytest.mark.xfail(
    strict=True,
    raises=SecondDefinition,
    reason=(
        "extra: decisions/loop-engine-epoch.md: section 2.3, moves 1 and 2. Waits for "
        "loop/tests/test_shared_run_vocabulary.py--test_effects_and_claims_are_declared_once and a planner restating "
        "the build claim tests on the std-loop kinds with their expectations unchanged. Then build/schema no longer "
        "declares BuildClaimActivity, BuildClaimDelete or BuildClaimRefRead; the lease and settling rules of "
        "build/rules/claims.dl and build/rules/claim_release.dl move to packs/std-loop/rules as claim_lease_ended, "
        "claim_held and the effect relations; and the build pack keeps build_claim_release_plan, build_claim_held, "
        "build_claim_released, build_claim_release_discarded and build_claim_release_pending with the same rows."
    ),
)
def test_build_claims_use_the_shared_kinds():
    build = classes(ROOT / "build" / "schema")
    kept = sorted(set(MOVED_KINDS) & set(build))
    if kept:
        raise SecondDefinition(f"build/schema still declares {kept}")
    rules = declared(ROOT / "build" / "rules")
    assert not set(MOVED_RULES) & rules, sorted(set(MOVED_RULES) & rules)
    assert set(KEPT_RULES) <= rules, sorted(set(KEPT_RULES) - rules)
    assert set(SHARED_RULES) <= declared(LOOP / "rules"), sorted(set(SHARED_RULES) - declared(LOOP / "rules"))


def shell(tmp_path, name, rule):
    """A pack that imports the production std-loop and adds one rule file of its own."""
    shutil.copytree(LOOP, tmp_path / "std-loop")
    shutil.copytree(ORDER, tmp_path / "std-order")
    from rezono_compiler import modules, pack

    app = tmp_path / name
    (app / "schema").mkdir(parents=True)
    (app / "schema" / "reader.yaml").write_text(
        f"id: https://example.org/{name}\n"
        f"name: {name.replace('-', '_')}\n"
        'imports: [linkml:types, "std-loop:loop_inputs", "std-loop:round_progress"]\n',
        encoding="utf-8",
    )
    (app / "pack.yaml").write_text(yaml.safe_dump({
        "name": name, "version": "0.1.0", "default_language": "en",
        "imports": [{"name": "std-loop", "path": "../std-loop", "sha256": modules.pack_hash(tmp_path / "std-loop")}],
    }), encoding="utf-8")
    (app / "channels.yaml").write_text("kinds: []\n", encoding="utf-8")
    (app / "labels").mkdir()
    (app / "labels" / "en.yaml").write_text("{}\n", encoding="utf-8")
    (app / "rules").mkdir()
    (app / "rules" / f"{name.replace('-', '_')}.dl").write_text(rule, encoding="utf-8")
    return pack.read(app)


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


GATE_RULE = """// A red reading of a required gate refuses the step that requires it.
derived_refusal(run, step, event) :-
    requirement(run, step, token, _),
    observed(run, token, _, event, "known", "red", _).
"""


def gate_records(value):
    return {
        "loop_active_run": [{"id": RUN}],
        "loop_step": [{"id": "check", "precedes": ["write"]}, {"id": "write"}],
        "loop_completion": [
            {"id": "def-check", "run": RUN, "step": "check", "token": "checked", "reason": "def-check"},
            {"id": "def-write", "run": RUN, "step": "write", "token": "written", "reason": "def-write"},
        ],
        "loop_requirement": [{"id": "needs-gate", "run": RUN, "step": "check", "token": "gate",
                              "reason": "needs-gate"}],
        "loop_expectation": [{"id": "gate", "value": "green"}, {"id": "checked", "value": "yes"},
                             {"id": "written", "value": "yes"}],
        "loop_observation": [{"id": "gate-reading", "run": RUN, "token": "gate", "event_time": 3, "state": "known",
                              "value": value, "reason": "gate-reading"}],
    }


def test_a_derived_refusal_makes_its_step_stuck(tmp_path):
    if not _std_loop_extensible("derived_refusal"):
        raise MissingExtension("packs/std-loop does not declare derived_refusal as extensible")
    model = shell(tmp_path, "gate-reader", GATE_RULE)
    program, rows, explainer = evaluate(model, gate_records("red"))
    refused = [row for row in rows.get("stuck", set()) if row[:2] == (RUN, "check")]
    assert refused, rows.get("stuck")
    assert any({"gate-reading", "needs-gate"} <= ground_ids(program, explainer, "stuck", row) for row in refused)
    assert not any(row[:2] == (RUN, "check") for row in rows.get("unblocked", set()))
    # The control: a green reading refuses nothing, and the gated step is unblocked.
    _, rows, _ = evaluate(model, gate_records("green"))
    assert not any(row[:2] == (RUN, "check") for row in rows.get("stuck", set()))
    assert any(row[:2] == (RUN, "check") for row in rows.get("unblocked", set()))


PERMIT_RULE = """// Every recorded plan of a step may go out.
effect_permitted(run, step, plan, plan) :-
    loop_effect_plan__run(plan, run), loop_effect_plan__step(plan, step).
"""
PLAN = "plan-1"


def effect_records(attempt=None, readback=None):
    data = {
        "loop_active_run": [{"id": RUN}],
        "loop_step": [{"id": "sign"}],
        "loop_completion": [{"id": "def-sign", "run": RUN, "step": "sign", "token": "signed", "reason": "def-sign"}],
        "loop_expectation": [{"id": "signed", "value": "yes"}],
        "loop_effect_plan": [{"id": PLAN, "run": RUN, "step": "sign", "reason": "statement"}],
    }
    if attempt is not None:
        data["loop_effect_attempt"] = [{"id": "attempt-1", "run": RUN, "plan": PLAN, "sent_at": 5,
                                        "outcome": attempt, "source": "journal"}]
    if readback is not None:
        state, at = readback
        data["loop_sweep_receipt"] = [{"id": f"cut-{at}", "run": RUN, "event_time": at}]
        data["loop_effect_readback"] = [{"id": "readback-1", "run": RUN, "plan": PLAN, "observed_at": at,
                                         "state": state, "receipt": f"cut-{at}", "source": "store"}]
    return data


# Worked by hand from decisions/loop-engine-epoch.md section 5: (attempt outcome, readback (state, tick)) ->
# planned, pending reason or None, confirmed, discarded, derived journal state.
EFFECT_CASES = [
    ((None, None), True, None, False, False, "planned"),
    (("claimed", None), False, "readback-missing", False, False, "applying"),
    (("unknown", None), False, "readback-missing", False, False, "unknown"),
    (("unknown", ("before", 7)), False, "still-before", False, False, "unknown"),
    # A readback older than the attempt does not settle it.
    (("unknown", ("expected", 4)), False, "readback-missing", False, False, "unknown"),
    (("sent", ("expected", 7)), False, None, True, False, "applied"),
    (("unknown", ("other", 7)), False, None, False, True, "failed"),
    (("refused", None), False, None, False, True, "failed"),
]


def test_an_effect_is_attempted_once_per_plan(tmp_path):
    if not _std_loop_extensible("effect_permitted"):
        raise MissingExtension("packs/std-loop does not declare effect_permitted as extensible")
    model = shell(tmp_path, "effect-reader", PERMIT_RULE)
    for (attempt, readback), planned, pending, confirmed, discarded, state in EFFECT_CASES:
        case = (attempt, readback)
        _, rows, _ = evaluate(model, effect_records(attempt, readback))
        assert ((RUN, "sign", PLAN) in {row[:3] for row in rows.get("effect_planned", set())}) is planned, case
        assert {row[2] for row in rows.get("effect_pending", set()) if row[:2] == (RUN, PLAN)} == (
            {pending} if pending else set()), case
        assert ((RUN, PLAN) in {row[:2] for row in rows.get("effect_confirmed", set())}) is confirmed, case
        assert ((RUN, PLAN) in {row[:2] for row in rows.get("effect_discarded", set())}) is discarded, case
        states = {row[2] for row in rows.get("effect_state", set()) if row[:2] == (RUN, PLAN)}
        assert states == {state}, case


def test_effect_stale_readback_between_attempts_cannot_settle(tmp_path):
    """A readback between an earlier claimed attempt and a later sent/unknown attempt never settles the plan."""
    model = shell(tmp_path, "effect-latest-reader", PERMIT_RULE)

    def records(attempts, readbacks):
        receipts = sorted({tick for _, tick in readbacks})
        return {
            "loop_active_run": [{"id": RUN}],
            "loop_step": [{"id": "sign"}],
            "loop_completion": [{"id": "def-sign", "run": RUN, "step": "sign", "token": "signed",
                                 "reason": "def-sign"}],
            "loop_expectation": [{"id": "signed", "value": "yes"}],
            "loop_effect_plan": [{"id": PLAN, "run": RUN, "step": "sign", "reason": "statement"}],
            "loop_effect_attempt": [
                {"id": f"attempt-{idx}", "run": RUN, "plan": PLAN, "sent_at": sent_at,
                 "outcome": outcome, "source": "journal"}
                for idx, (outcome, sent_at) in enumerate(attempts, start=1)
            ],
            "loop_sweep_receipt": [{"id": f"cut-{tick}", "run": RUN, "event_time": tick} for tick in receipts],
            "loop_effect_readback": [
                {"id": f"readback-{idx}", "run": RUN, "plan": PLAN, "observed_at": tick,
                 "state": state, "receipt": f"cut-{tick}", "source": "store"}
                for idx, (state, tick) in enumerate(readbacks, start=1)
            ],
        }

    cases = [
        # Stale expected readback between claimed@5 and sent@10 must leave the plan pending.
        ("stale_expected_between_claimed_and_sent",
         [("claimed", 5), ("sent", 10)], [("expected", 7)],
         "10", "readback-missing", False, False, "unknown"),
        # Stale other readback between claimed@5 and unknown@10 must not discard the plan.
        ("stale_other_between_claimed_and_unknown",
         [("claimed", 5), ("unknown", 10)], [("other", 7)],
         "10", "readback-missing", False, False, "unknown"),
        # Stale before readback between claimed@5 and sent@10 must not report still-before.
        ("stale_before_between_claimed_and_sent",
         [("claimed", 5), ("sent", 10)], [("before", 7)],
         "10", "readback-missing", False, False, "unknown"),
        # Readback at the exact tick of the latest attempt does not settle it.
        ("readback_at_latest_attempt_tick",
         [("claimed", 5), ("sent", 10)], [("expected", 10)],
         "10", "readback-missing", False, False, "unknown"),
        # Stale other@7 must not block a fresh expected@12 after sent@10 from confirming.
        ("stale_other_superseded_by_fresh_expected",
         [("claimed", 5), ("sent", 10)], [("other", 7), ("expected", 12)],
         "10", None, True, False, "applied"),
        # Stale expected@7 must not settle ahead of a fresh other@12 after unknown@10.
        ("stale_expected_superseded_by_fresh_other",
         [("claimed", 5), ("unknown", 10)], [("expected", 7), ("other", 12)],
         "10", None, False, True, "failed"),
        # Fresh before@12 after sent@10 reports still-before.
        ("fresh_before_after_latest_attempt",
         [("claimed", 5), ("sent", 10)], [("before", 12)],
         "10", "still-before", False, False, "unknown"),
    ]

    for name, attempts, readbacks, latest, pending, confirmed, discarded, state in cases:
        _, rows, _ = evaluate(model, records(attempts, readbacks))
        assert rows.get("effect_latest_attempt") == {(RUN, PLAN, latest)}, name
        assert {row[2] for row in rows.get("effect_pending", set()) if row[:2] == (RUN, PLAN)} == (
            {pending} if pending else set()), name
        assert ((RUN, PLAN) in {row[:2] for row in rows.get("effect_confirmed", set())}) is confirmed, name
        assert ((RUN, PLAN) in {row[:2] for row in rows.get("effect_discarded", set())}) is discarded, name
        states = {row[2] for row in rows.get("effect_state", set()) if row[:2] == (RUN, PLAN)}
        assert states == {state}, name
