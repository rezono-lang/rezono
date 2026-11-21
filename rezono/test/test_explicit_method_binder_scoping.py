"""Normalization and scoping of explicit method binders (`S.any(x: ...)`, `S.where(x: ...)`):

1. `normalQuestion()` collects every explicit method binder into `avoid` so a valid `ask` never
   normalizes into an `R011` duplicate binder when the method body only uses bare slots or no paths.
2. Explicit method binders shadow bare slots of outer levels and the same kind instead of raising
   false `R011` collisions, while preserving `R011` for implicit `it` and `ask` binder shadowing.
3. `it` is forbidden as an explicit method binder (refused with `R011` at the binder span without
   a self-contradictory `R001`/`hint.row` diagnostic), and explicit method binders colliding with
   `schema.params` are refused with `R011` at the binder span.
"""

import json
from pathlib import Path
import subprocess

from reader_probe import at

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = {
    "rezono": "0",
    "pack": "sample",
    "base": "https://rezono.example/sample/",
    "params": {
        "threshold": {"type": "Integer", "states": ["known"]},
    },
    "kinds": {
        "Item": {
            "world": "closed",
            "slots": {
                "items": {"ref": "Child", "card": "*", "states": ["known"]},
            },
        },
        "Child": {
            "world": "closed",
            "slots": {
                "flag": {"type": "Bool", "card": "1", "states": ["known"]},
            },
        },
        "Inner": {
            "world": "closed",
            "slots": {
                "active": {"type": "Bool", "card": "1", "states": ["known"]},
            },
        },
        "Outer": {
            "world": "closed",
            "slots": {
                "child": {"ref": "Inner", "card": "1", "states": ["known"]},
            },
        },
        "Node": {
            "world": "closed",
            "slots": {
                "node": {"ref": "Node", "card": "?", "states": ["known", "not_applicable"]},
                "active": {"type": "Bool", "card": "1", "states": ["known"]},
            },
        },
    },
}

MODULE_SHADOWING = """\
rezono 1
pack sample
kind Inner
  active: Bool
kind Outer
  child: Inner
  derived ok: Bool = Inner.any(child: child.active)
kind Node
  node: Node?
  active: Bool
derived any_node(seed: Node): Bool = Node.any(node: node.active and node != seed)
"""

MODULE_FORBIDDEN_IT = """\
rezono 1
pack sample
kind Child
  flag: Bool
kind Item
  items: Child*
derived bad_it(x: Item): Bool = x.items.any(it: it.flag)
"""

MODULE_PARAM_COLLISION = """\
rezono 1
pack sample
param threshold: Int
kind Child
  flag: Bool
kind Item
  items: Child*
derived bad_param(x: Item): Bool = x.items.any(threshold: flag)
"""

PROBE = """\
import { check, checkModule, normalQuestion, print, questionHash } from './rezono/src/index.ts';

const payload = JSON.parse(process.argv[1]);
const diagOf = (d) => ({
  code: d.code,
  args: d.args ?? [],
  span: d.span,
  ...(d.hint ? { hint: d.hint } : {}),
});

const questions = [];
for (const text of payload.questions ?? []) {
  const checked = check(text, payload.schema);
  const entry = {
    text,
    diagnostics: checked.diagnostics.map(diagOf),
  };
  if (checked.tree && !checked.diagnostics.some((d) => !d.code.startsWith('W'))) {
    const normTree = normalQuestion(checked, payload.schema);
    const normalized = print(normTree);
    const rechecked = check(normalized, payload.schema);
    const renormalized = rechecked.tree ? print(normalQuestion(rechecked, payload.schema)) : null;
    entry.normalized = normalized;
    entry.rechecked_diagnostics = rechecked.diagnostics.map(diagOf);
    entry.idempotent = renormalized === normalized;
    entry.hash = await questionHash(checked, payload.schema);
  }
  questions.push(entry);
}

const modules = (payload.modules ?? []).map((source) => {
  const checked = checkModule(source);
  return {
    diagnostics: checked.diagnostics.map(diagOf),
  };
});

process.stdout.write(JSON.stringify({ questions, modules }));
"""


def run_probe(questions=(), modules=()):
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            PROBE,
            json.dumps({"schema": SCHEMA, "questions": list(questions), "modules": list(modules)}),
        ],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_normal_question_avoids_explicit_method_binder_collisions():
    q_bare_slot = "ask i: Item where items.any(item: flag)"
    q_explicit_slot = "ask x: Item where x.items.any(item: item.flag)"
    q_no_paths = "ask i: Item where items.any(item: true)"
    q_filter = "ask i: Item where items.where(item: flag).count() > 0"
    q_show = "ask i: Item where true show items.any(item: true)"

    out = run_probe(questions=[q_bare_slot, q_explicit_slot, q_no_paths, q_filter, q_show])
    bare, explicit, no_paths, filt, show = out["questions"]

    for entry in (bare, explicit, no_paths, filt, show):
        assert entry["diagnostics"] == [], entry
        assert entry["rechecked_diagnostics"] == [], entry
        assert entry["idempotent"] is True, entry

    assert bare["normalized"] == "ask item_2: Item where item_2.items.any(item: item.flag)"
    assert bare["hash"] == explicit["hash"]
    assert no_paths["normalized"] == "ask item_2: Item where item_2.items.any(item: true)"
    assert filt["normalized"] == "ask item_2: Item where 0 < item_2.items.where(item: item.flag).count()"
    assert show["normalized"] == "ask item_2: Item where true show item_2.items.any(item: true)"


def test_explicit_method_binder_shadows_outer_and_same_kind_slots():
    q_outer_slot = "ask o: Outer where Inner.any(child: child.active)"
    q_same_kind_slot = "ask n: Node where Node.any(node: node.active)"
    q_ask_binder_collision = "ask child: Outer where child = inner-1"

    out = run_probe(
        questions=[q_outer_slot, q_same_kind_slot, q_ask_binder_collision],
        modules=[MODULE_SHADOWING],
    )
    outer_q, node_q, ask_collision = out["questions"]
    [mod_shadowing] = out["modules"]

    assert mod_shadowing["diagnostics"] == [], mod_shadowing
    for entry in (outer_q, node_q):
        assert entry["diagnostics"] == [], entry
        assert entry["rechecked_diagnostics"] == [], entry
        assert entry["idempotent"] is True, entry

    # Explicit `ask` binder colliding with its own slot still raises R011 (§5 rule 7).
    assert [d["code"] for d in ask_collision["diagnostics"]] == ["R011"], ask_collision


def test_explicit_method_binder_forbids_it_and_param_collisions():
    q_it_used = "ask i: Item where items.any(it: it.flag)"
    q_it_unused = "ask i: Item where items.any(it: true)"
    q_it_filter = "ask i: Item where items.where(it: it.flag).count() > 0"
    q_param_unused = "ask i: Item where items.any(threshold: flag)"
    q_param_used = "ask i: Item where items.any(threshold: threshold.flag)"

    out = run_probe(
        questions=[q_it_used, q_it_unused, q_it_filter, q_param_unused, q_param_used],
        modules=[MODULE_FORBIDDEN_IT, MODULE_PARAM_COLLISION],
    )
    it_used, it_unused, it_filter, param_unused, param_used = out["questions"]
    mod_it, mod_param = out["modules"]

    for q, entry in ((q_it_used, it_used), (q_it_unused, it_unused), (q_it_filter, it_filter)):
        assert entry["diagnostics"] == [
            {"code": "R011", "args": ["it"], "span": at(q, "it", after="(")}
        ], entry

    assert mod_it["diagnostics"] == [
        {"code": "R011", "args": ["it"], "span": at(MODULE_FORBIDDEN_IT, "it", after="any(")}
    ], mod_it

    assert param_unused["diagnostics"] == [
        {"code": "R011", "args": ["threshold"], "span": at(q_param_unused, "threshold", after="any(")}
    ], param_unused
    assert any(
        d["code"] == "R011" and d["span"] == at(q_param_used, "threshold", after="any(")
        for d in param_used["diagnostics"]
    ), param_used
    assert mod_param["diagnostics"] == [
        {"code": "R011", "args": ["threshold"], "span": at(MODULE_PARAM_COLLISION, "threshold", after="any(")}
    ], mod_param
