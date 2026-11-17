"""The semantic type model (S3a, B09): each case is represented once, and every projection gives exactly the
names the compiler's outputs used before B09, so routing the compiler through it changes no byte."""

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import genpack
from rezono_compiler import calc, pack, types

ROOT = Path(__file__).resolve().parents[2]
# The tables the compiler kept before B09, one per consumer: the reference these projections must equal.
LINKML_SQL = {"string": "VARCHAR", "integer": "BIGINT", "boolean": "BOOLEAN", "date": "DATE"}
SQL_BUNDLE = {"VARCHAR": "text", "BIGINT": "integer", "BOOLEAN": "boolean", "DATE": "date"}
SQL_RULE = {"VARCHAR": "string", "BIGINT": "integer"}
# Every example pack (the standard packs in packs/ are imported by these, not compiled alone).
PACKS = sorted(p.parent for p in ROOT.glob("examples/**/pack.yaml"))


def test_each_case_is_represented_once():
    cases = {
        "scalar": types.scalar(types.STRING, "string"),
        "quantity": types.quantity("cents"),
        "money": types.money("EUR", "amount"),
        "date": types.scalar(types.DATE, "date"),
        "enum": types.enum("status"),
        "ref": types.ref("team", types.STRING),
        "derived": types.derived("hourly_price", types.NUMBER),
    }
    assert {name: t.case for name, t in cases.items()} == {name: name for name in cases}
    # An open enum is representable; no reader makes one yet.
    assert types.enum("status", open=True).case == "enum" and types.enum("status", open=True).open
    # A derived number keeps its unit, and is still derived.
    assert types.Type(types.NUMBER, unit="cents", derived="price").case == "derived"
    # Money is whole minor units: stored and named as an integer, with its currency beside it.
    assert (cases["money"].sql, cases["money"].bundle, cases["money"].calc) == ("BIGINT", "integer", types.NUMBER)
    # A reference is stored as its target root's identifier and is never a calc value.
    assert (cases["ref"].sql, cases["ref"].rule, cases["ref"].calc) == ("VARCHAR", "string", None)
    assert types.ref("team", types.INTEGER).sql == "BIGINT"
    # An enum is its text key in the engine, `enum` in the bundle, and no calc value.
    assert (cases["enum"].sql, cases["enum"].bundle, cases["enum"].calc) == ("VARCHAR", "enum", None)
    # A calc number has no single SQL column.
    with pytest.raises(ValueError):
        cases["quantity"].sql
    with pytest.raises(ValueError):
        types.ref("team", types.DATE)
    with pytest.raises(ValueError):
        types.Type("float")


def test_projections_equal_the_tables_they_replace():
    for linkml, sql in LINKML_SQL.items():
        assert types.linkml(linkml) == linkml and types.scalar(linkml).sql == sql
        assert types.of_sql(sql).bundle == SQL_BUNDLE[sql]
        assert types.rule_type(sql) == SQL_RULE.get(sql)
        assert types.of_sql(sql).calc == {"BIGINT": "number", "BOOLEAN": "boolean"}.get(sql)
    for root in ("float", "double", "decimal", "datetime", "uri"):
        assert types.linkml(root) is None
    assert types.FLOATING == {"float", "double", "decimal"}
    assert (calc.NUMBER, calc.BOOLEAN) == (types.NUMBER, types.BOOLEAN)


def old_names(s) -> tuple:
    """What the compiler computed from a slot before B09: engine type, bundle type, calc type."""
    return (s.sql_type, "enum" if s.enum else SQL_BUNDLE[s.sql_type],
            None if s.arrow else {"BIGINT": "number", "BOOLEAN": "boolean"}.get(s.sql_type))


def assert_slots_unchanged(p) -> int:
    n = 0
    for kind in p.kinds.values():
        for s in kind.slots.values():
            t = types.of_slot(s)
            assert (t.sql, t.bundle, t.calc) == old_names(s), s.element
            assert (t.target, t.enum, t.currency) == ((s.range if s.arrow else None), s.enum, s.currency), s.element
            n += 1
    return n


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda d: str(d.relative_to(ROOT)))
def test_every_slot_of_every_pack_keeps_its_names(pack_dir):
    p = pack.read(pack_dir)
    assert_slots_unchanged(p)
    if p.calc is not None:
        prog = calc.build(p, p.calc)
        for rule in prog.rules:
            r = prog.result(rule)
            assert (r.case, r.base, r.derived) == ("derived", prog.types[rule], rule)
            assert r.unit is None or r.base == types.NUMBER


def test_the_examples_cover_every_case_read_from_a_pack():
    seen = set()
    for pack_dir in PACKS:
        p = pack.read(pack_dir)
        seen |= {types.of_slot(s).case for k in p.kinds.values() for s in k.slots.values()}
        if p.calc is not None:
            prog = calc.build(p, p.calc)
            seen |= {prog.result(r).case for r in prog.rules}
    assert {"scalar", "date", "enum", "ref", "money", "derived"} <= seen


@settings(max_examples=30, deadline=None)
@given(st.data())
def test_random_packs_keep_their_names(data):
    spec = genpack.draw_spec(data.draw)
    if spec.refused():
        return
    with tempfile.TemporaryDirectory() as tmp:
        genpack.write_pack(spec, Path(tmp) / "pack")
        assert_slots_unchanged(pack.read(Path(tmp) / "pack"))


def test_the_semantic_type_writes_what_the_model_knows_and_nothing_else():
    # B10: each case as the bundle writes it; a field without a value is left out, never null.
    assert types.scalar(types.STRING, "string").semantic == {"case": "scalar", "base": "string", "range": "string"}
    assert types.money("EUR", "Cents").semantic == {"case": "money", "base": "integer", "range": "Cents", "currency": "EUR"}
    assert types.quantity("cents").semantic == {"case": "quantity", "base": "number", "unit": "cents"}
    assert types.enum("status").semantic == {"case": "enum", "base": "string", "range": "status", "enum": "status"}
    assert types.enum("status", open=True).semantic["open"] is True
    assert types.ref("team", types.STRING).semantic == {"case": "ref", "base": "string", "range": "team", "target": "team"}
    assert types.derived("total", types.NUMBER).semantic == {"case": "derived", "base": "number", "derived": "total"}


GOLDEN = Path("expected/compiled/bundle/schema-bundle.json")


@pytest.mark.parametrize("pack_dir", [d for d in PACKS if (d / GOLDEN).exists()], ids=lambda d: str(d.relative_to(ROOT)))
def test_every_published_slot_carries_its_semantic_type(pack_dir):
    # B10: the bundle of every example names, per slot, the type the compiler holds; per calc view its result.
    import json
    from rezono_compiler import emit
    published = json.loads((pack_dir / GOLDEN).read_text())
    p = pack.read(pack_dir)
    want = {s.element: s.type.semantic for k in p.kinds.values() for s in k.slots.values()}
    got = {s["id"]: s.get("semantic") for s in published.get("arrows", []) + published.get("attributes", [])}
    assert got == want
    for s in published.get("arrows", []):
        assert s["semantic"]["case"] == "ref" and s["semantic"]["target"] == s["target"]
    views = [r for r in published.get("relations", []) if "calc" in r]
    if views:
        prog = calc.build(p, p.calc)
        assert {r["id"]: r["semantic"] for r in views} == {r["id"]: emit.calc_semantic(prog, r["calc"]) for r in views}
