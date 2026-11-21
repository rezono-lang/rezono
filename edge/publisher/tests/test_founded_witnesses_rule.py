"""Planner red test requiring a real Rezono rule over the witness graph (decisions/publish-founded-witnesses.md).

Verifies that founded alternatives (`founded_witness`) and load-bearing premises (`load_bearing`) are
derived by an actual compiled Rezono rule pack over the role's witness graph — never computed only in
ad-hoc Python inside `edge/publisher` or `checker`:
- `access.for_role` evaluates a checked-in Rezono rule pack through `rezono_compiler.batch` and fails
  closed if that rule evaluation is unavailable;
- the rule pack compiles cleanly via `rezono_compiler.pack.read` and defines `founded_witness/3` and
  `load_bearing/5` as derived relations where `load_bearing` genuinely derives universal support over
  `founded_witness` (using negation or aggregation, not a pass-through of precomputed Python flags);
- on a concrete witness graph with two founded alternatives sharing one load-bearing premise (`anchor(a)`)
  and two non-load-bearing alternative premises (`edge(b,a)`, `edge(a,b)`), the rule derives both
  `founded_witness` rows and only `anchor(a)` in `load_bearing`;
- on the single-witness counterexample (only `near_in(a,b)` present), the rule derives one
  `founded_witness` row and marks every premise (`anchor(a)` and `edge(b,a)`) as `load_bearing`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from rezono_compiler import batch as compiler_batch
from rezono_compiler import pack as compiler_pack
from rezono_compiler import rules as compiler_rules
from rezono_publisher import access

ROOT = Path(__file__).resolve().parents[3]
SKIP_PACK_DIRS = {"tests", "test", "fixtures", "fixture", "node_modules", ".venv", "__pycache__"}

KINDS = {"node", "role"}
COLUMNS = {
    "node": ("node",),
    "role": ("role",),
    "anchor": ("node",),
    "edge": ("node", "node"),
    "near": ("node", "node"),
}


def _lit(rel, *terms, stratum=0):
    return {"relation": rel, "terms": list(terms), "polarity": "positive", "stratum": stratum}


def _rel(name, role, arity):
    return {"name": name, "role": role, "key": [{"name": f"c{i}", "type": "string"} for i in range(arity)]}


def _key(*parts):
    return json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)


def _witness(rid, head, bindings, premises):
    return {
        "conclusion": {"relation": head[0], "key": _key(*head[1:])},
        "rule_id": rid,
        "bindings": [{"variable": v, "value": x} for v, x in bindings],
        "premises": [
            {"row": {"relation": p[0], "key": _key(*p[1:])}, "polarity": "positive", "stratum": s}
            for p, s in premises
        ],
    }


RULES = {
    "format": "rezono.rules/1",
    "pack": "witness_graph_rule_test",
    "relations": [
        _rel("node", "base", 1),
        _rel("role", "base", 1),
        _rel("may_read", "derived", 3),
        _rel("anchor", "base", 1),
        _rel("edge", "base", 2),
        _rel("near", "derived", 2),
    ],
    "rules": [
        {
            "id": "near_in",
            "stratum": 1,
            "head": {"relation": "near", "terms": ["?a", "?b"]},
            "body": [_lit("anchor", "?a", stratum=0), _lit("edge", "?b", "?a", stratum=0)],
        },
        {
            "id": "near_out",
            "stratum": 1,
            "head": {"relation": "near", "terms": ["?a", "?b"]},
            "body": [_lit("anchor", "?a", stratum=0), _lit("edge", "?a", "?b", stratum=0)],
        },
    ],
}


def _find_checked_in_pack(pack_name: str) -> Path | None:
    """Locate the checked-in rule pack directory whose `pack.yaml` declares `name: pack_name`."""
    candidates: list[Path] = []
    for base in (ROOT / "packs", ROOT / "edge", ROOT / "checker", ROOT / "compiler"):
        if not base.is_dir():
            continue
        for manifest in sorted(base.rglob("pack.yaml")):
            rel_parts = set(manifest.relative_to(ROOT).parts[:-1])
            if rel_parts & SKIP_PACK_DIRS:
                continue
            candidates.append(manifest)
    for manifest in candidates:
        meta = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        if isinstance(meta, dict) and meta.get("name") == pack_name:
            return manifest.parent
    return None


def _transitive_deps(prog, relation: str) -> set[str]:
    """All relations that `relation` depends on directly or transitively in `prog`."""
    seen: set[str] = set()
    stack = [relation]
    while stack:
        current = stack.pop()
        for dep in prog.deps(current):
            if dep not in seen:
                seen.add(dep)
                if dep in prog.relations and prog.relations[dep].role in ("derived", "functional"):
                    stack.append(dep)
    return seen


def _has_universal_rule_structure(prog, relation: str) -> bool:
    """Whether `relation` or a derived helper it depends on uses negation or aggregation."""
    closure = {relation} | {
        dep for dep in _transitive_deps(prog, relation)
        if dep in prog.relations and prog.relations[dep].role in ("derived", "functional")
    }
    for rel in closure:
        for rule in prog.rules_for(rel):
            if rule.aggregates or any(lit.polarity == "negative" for lit in rule.body):
                return True
    return False


def _collect_witness_rule_eval(reads):
    """Merge `batch.read` calls per pack and return `(prog, rows)` for the pack deriving both relations."""
    programs = {}
    merged: dict[str, dict[str, set[tuple[str, ...]]]] = {}
    for prog, rows in reads:
        programs[prog.pack] = prog
        merged.setdefault(prog.pack, {}).update(rows)
    for pack_name, rows in merged.items():
        if {"founded_witness", "load_bearing"} <= set(rows):
            return programs[pack_name], rows
    return None, None


def test_witness_graph_rule_derives_founded_witness_and_load_bearing(monkeypatch):
    reads: list[tuple[object, dict[str, set[tuple[str, ...]]]]] = []
    real_read = compiler_batch.read

    def spy_read(con, prog, names=None):
        rows = real_read(con, prog, names)
        reads.append((prog, rows))
        return rows

    monkeypatch.setattr(compiler_batch, "read", spy_read)

    w_in = _witness(
        "near_in",
        ("near", "a", "b"),
        [("?a", "a"), ("?b", "b")],
        [(("anchor", "a"), 0), (("edge", "b", "a"), 0)],
    )
    w_out = _witness(
        "near_out",
        ("near", "a", "b"),
        [("?a", "a"), ("?b", "b")],
        [(("anchor", "a"), 0), (("edge", "a", "b"), 0)],
    )

    # Case 1: two founded alternatives for near(a,b):
    # - anchor(a) is shared by both alternatives -> load_bearing.
    # - edge(b,a) and edge(a,b) are each omitted by the other alternative -> not load_bearing.
    rows_two = {
        "node": [("a",), ("b",)],
        "role": [("all_reader",)],
        "anchor": [("a",)],
        "edge": [("a", "b"), ("b", "a")],
        "near": [("a", "b")],
        "may_read": [("all_reader", "node", "a"), ("all_reader", "node", "b")],
    }
    _, sees_two, _ = access.for_role(rows_two, KINDS, {}, COLUMNS, RULES, [w_out, w_in], "all_reader")

    prog, derived_two = _collect_witness_rule_eval(reads)
    assert prog is not None and derived_two is not None, (
        "access.for_role must evaluate a Rezono rule pack via rezono_compiler.batch deriving "
        f"founded_witness and load_bearing; observed batch.read calls: {[(p.pack, sorted(r)) for p, r in reads]}"
    )

    # Verify the rule pack exists on disk in the repository, compiles cleanly, and genuinely derives
    # both relations over the witness graph (forbidding inline stubs or Python-precomputed pass-throughs).
    pack_dir = _find_checked_in_pack(prog.pack)
    assert pack_dir is not None, (
        f"witness-graph rule pack {prog.pack!r} must be a checked-in pack under packs/, edge/, checker/, or compiler/"
    )
    compiled_model = compiler_pack.read(pack_dir)
    compiled_prog = compiler_rules.load(compiled_model.rules)
    for rel_name, expected_arity in (("founded_witness", 3), ("load_bearing", 5)):
        assert rel_name in compiled_prog.derived(), f"pack {prog.pack!r} must derive {rel_name}"
        assert len(compiled_prog.relations[rel_name].key) == expected_arity, (
            f"{rel_name} must have arity {expected_arity}, got {len(compiled_prog.relations[rel_name].key)}"
        )
        assert compiled_prog.rules_for(rel_name), f"pack {prog.pack!r} must declare at least one rule for {rel_name}"
    assert "founded_witness" in _transitive_deps(compiled_prog, "load_bearing"), (
        f"load_bearing in pack {prog.pack!r} must depend on founded_witness over the witness graph"
    )
    assert _has_universal_rule_structure(compiled_prog, "load_bearing"), (
        f"load_bearing in pack {prog.pack!r} must derive universal support via negation or aggregation, "
        "not copy precomputed Python flags"
    )

    near_key = _key("a", "b")
    fw_two = {r for r in derived_two["founded_witness"] if r[:2] == ("near", near_key)}
    assert len(fw_two) == 2 and all(r[2] for r in fw_two), (
        f"expected 2 distinct founded_witness rows for near(a,b), got {sorted(fw_two)}"
    )
    lb_two = {r for r in derived_two["load_bearing"] if r[:2] == ("near", near_key)}
    assert lb_two == {("near", near_key, "anchor", _key("a"), "positive")}, (
        f"expected only shared premise anchor(a) in load_bearing for two alternatives, got {sorted(lb_two)}"
    )

    near_ws_two = [w for w in sees_two["witnesses"] if w["conclusion"] == {"relation": "near", "key": near_key}]
    assert [w["rule_id"] for w in near_ws_two] == ["near_in", "near_out"]
    assert "load_bearing" in sees_two
    assert sees_two["load_bearing"][("near", near_key, "anchor", _key("a"), "positive")] is True
    assert sees_two["load_bearing"][("near", near_key, "edge", _key("b", "a"), "positive")] is False
    assert sees_two["load_bearing"][("near", near_key, "edge", _key("a", "b"), "positive")] is False

    # Case 2 (counterexample): single founded witness -> every premise of that witness is load_bearing.
    reads.clear()
    rows_one = {**rows_two, "edge": [("b", "a")]}
    _, sees_one, _ = access.for_role(rows_one, KINDS, {}, COLUMNS, RULES, [w_in], "all_reader")

    prog_one, derived_one = _collect_witness_rule_eval(reads)
    assert prog_one is not None and derived_one is not None, (
        "single-witness graph must also be evaluated through the witness-graph rule pack"
    )
    fw_one = {r for r in derived_one["founded_witness"] if r[:2] == ("near", near_key)}
    assert len(fw_one) == 1 and all(r[2] for r in fw_one), (
        f"expected 1 founded_witness row for single-witness near(a,b), got {sorted(fw_one)}"
    )
    lb_one = {r for r in derived_one["load_bearing"] if r[:2] == ("near", near_key)}
    assert lb_one == {
        ("near", near_key, "anchor", _key("a"), "positive"),
        ("near", near_key, "edge", _key("b", "a"), "positive"),
    }, f"expected every premise of single witness in load_bearing, got {sorted(lb_one)}"

    near_ws_one = [w for w in sees_one["witnesses"] if w["conclusion"] == {"relation": "near", "key": near_key}]
    assert [w["rule_id"] for w in near_ws_one] == ["near_in"]
    assert sees_one["load_bearing"][("near", near_key, "anchor", _key("a"), "positive")] is True
    assert sees_one["load_bearing"][("near", near_key, "edge", _key("b", "a"), "positive")] is True

    # Fail closed: access.for_role must not silently fall back to Python when rule evaluation fails.
    def broken_read(*_args, **_kwargs):
        raise RuntimeError("simulated witness-graph rule failure")

    monkeypatch.setattr(compiler_batch, "read", broken_read)
    with pytest.raises(RuntimeError, match="simulated witness-graph rule failure"):
        access.for_role(rows_one, KINDS, {}, COLUMNS, RULES, [w_in], "all_reader")
