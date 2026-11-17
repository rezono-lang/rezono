"""B11: an element is its root kind plus its id. Equal ids of different kinds never collapse; along
inheritance an element keeps one identity; a union's injection is deterministic and invertible."""

import shutil
from pathlib import Path

import pytest
import yaml

import souffle
from support import FIXTURE, typed
from rezono_compiler import batch, identity, pack, rules as ir


def edited(tmp_path, change=None) -> pack.Pack:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema["classes"]["Child"] = {"is_a": "Alpha"}
    schema["classes"]["Gamma"] = {"attributes": {"id": {"identifier": True, "range": "integer"}}}
    if change:
        change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
    channels = yaml.safe_load((d / "channels.yaml").read_text(encoding="utf-8"))
    channels["kinds"] += [{"kind": "child", "shape": "rect"}, {"kind": "gamma", "shape": "rect"}]
    (d / "channels.yaml").write_text(yaml.safe_dump(channels, sort_keys=False), encoding="utf-8")
    return pack.read(d)


@pytest.fixture
def model(tmp_path):
    return edited(tmp_path)


def test_an_element_is_its_root_and_its_id(model):
    assert identity.of(model, "alpha", "x") == identity.Identity("alpha", "x")
    assert identity.of(model, "beta", "x") == identity.Identity("beta", "x")
    assert identity.of(model, "alpha", "x") != identity.of(model, "beta", "x")
    # A subkind's element is its root's element with that id: one identity along inheritance.
    assert identity.of(model, "child", "x") == identity.of(model, "alpha", "x")
    assert identity.of(model, "gamma", 7) == identity.Identity("gamma", 7)


@pytest.mark.parametrize("kind, value", [("alpha", 7), ("gamma", "7"), ("gamma", True), ("missing", "x")])
def test_an_id_of_the_wrong_type_or_kind_is_refused(model, kind, value):
    with pytest.raises(identity.IdentityError):
        identity.of(model, kind, value)


def test_a_union_over_several_roots_keys_by_root_and_id(model):
    u = identity.union(model, ["beta", "alpha", "child"])
    assert u == identity.Union(("alpha", "beta"), "VARCHAR") and u.tagged
    assert u.columns() == (("kind", "string"), ("id", "string"))
    for element in (identity.Identity("alpha", "x"), identity.Identity("beta", "x")):
        assert u.element(u.key(element)) == element
    assert u.key(identity.Identity("alpha", "x")) != u.key(identity.Identity("beta", "x"))
    with pytest.raises(identity.IdentityError, match="not a root of the union"):
        u.key(identity.Identity("gamma", 1))


def test_a_union_over_one_root_is_the_id_alone(model):
    u = identity.union(model, ["alpha", "child"])
    assert u == identity.Union(("alpha",), "VARCHAR") and not u.tagged
    assert u.columns() == (("id", "string"),)
    assert u.key(identity.of(model, "child", "x")) == ("x",)
    assert u.element(("x",)) == identity.Identity("alpha", "x")
    assert identity.union(model, ["gamma"]).columns() == (("id", "integer"),)


def test_a_union_of_roots_with_different_identifier_types_is_refused(model):
    with pytest.raises(identity.IdentityError, match="different identifier types"):
        identity.union(model, ["alpha", "gamma"])
    with pytest.raises(identity.IdentityError, match="at least one"):
        identity.union(model, [])


def union_program(model, kinds):
    """The ordinary rule IR of a theory kind `node` populated from `kinds` by the identity injection."""
    u = identity.union(model, kinds)
    rules = [{"id": f"node_{i}", "module": "view", "head": {"relation": "node", "terms": list(terms)},
              "body": [{"relation": kind, "terms": ["?v0"], "polarity": "positive"}],
              "origin": {"file": "views.yaml", "line": "0"}}
             for i, (kind, terms) in enumerate(identity.injection(model, kinds))]
    relations = [{"name": k, "role": "base", "key": [{"name": "id", "type": "string"}]} for k in sorted(set(kinds))]
    relations.append({"name": "node", "role": "derived", "module": "view", "explain": "on_demand",
                      "key": [{"name": n, "type": t} for n, t in u.columns()]})
    return ir.load(ir.with_strata({"format": ir.FORMAT, "pack": model.meta["name"],
                                   "relations": relations, "rules": rules}))


def run(program, data):
    con = batch.connect(program, {n: typed(program, n, rows) for n, rows in data.items()}, threads=1)
    try:
        batch.compute(con, program)
        return batch.read(con, program, ["node"])["node"]
    finally:
        con.close()


DATA = {"alpha": [("x",), ("y",)], "beta": [("x",)]}


def test_a_union_of_two_kinds_with_equal_ids_keeps_both(model):
    program = union_program(model, ["alpha", "beta"])
    rows = run(program, DATA)
    assert rows == {("alpha", "x"), ("alpha", "y"), ("beta", "x")}
    u = identity.union(model, ["alpha", "beta"])
    assert {u.element(r) for r in rows} == {identity.of(model, k, v) for k, rs in DATA.items() for (v,) in rs}


def test_a_union_of_a_kind_and_its_subkind_holds_an_element_once(model):
    program = union_program(model, ["alpha", "child"])
    assert run(program, {"alpha": [("x",)], "child": [("x",)]}) == {("x",)}


@pytest.mark.skipif(shutil.which("souffle") is None, reason="Souffle is not installed; no oracle pass claimed")
def test_souffle_agrees_that_equal_ids_of_two_kinds_stay_two(model):
    program = union_program(model, ["alpha", "beta"])
    assert souffle.run(program, DATA)["node"] == run(program, DATA)
