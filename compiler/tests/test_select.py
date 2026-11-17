"""Selection's inventory, simultaneous plan and text edits, without a local engine run."""

from pathlib import Path
import shutil

import pytest
import yaml

from support import FIXTURE
from rezono_compiler import facts, operate, selection
from rezono_compiler.plan import evaluate


@pytest.fixture
def source(tmp_path):
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "facts").mkdir()
    (d / "facts" / "data.yaml").write_text(
        'alpha:\n  - {id: a, title: First, size: 3}\nbeta:\n  - {id: b, alpha: a, state: low}\n')
    return d


def choose(**changes):
    return {"op": "select", "keep": [{"kind": "Alpha"}],
            "omit": [{"kind": "Beta", "reason": "Outside the selected core"}], "accept_loss": True, **changes}


def test_plan_keeps_the_selected_rows_once_and_reports_all_omitted_cells(source):
    m = operate.model(source)
    step = selection.SelectOp(m, choose())
    plan = step.plan(None)
    rows = facts.load(m.pack, source / "facts/data.yaml")
    kept, lost, conflicts = evaluate(plan.forward, plan.gone, rows, plan.checks)
    assert not conflicts
    assert {k: v for k, v in kept.items() if v} == {k: v for k, v in rows.items() if k.startswith("alpha")}
    assert {k: v for k, v in lost.items() if v} == {k: v for k, v in rows.items() if k.startswith("beta")}
    assert plan.backward is None


@pytest.mark.parametrize("op", [choose(), choose(keep=[{"kind": "Alpha"}, {"kind": "Beta"}], omit=[])])
def test_selection_is_idempotent_and_preserves_duplicate_surviving_rows(source, op):
    m = operate.model(source)
    p = selection.SelectOp(m, op).plan(None)
    rows = facts.load(m.pack, source / "facts/data.yaml")
    rows["alpha"].append(rows["alpha"][0])
    first, _, conflicts = evaluate(p.forward, p.gone, rows)
    second, loss, more_conflicts = evaluate(p.forward, p.gone, first)
    assert first == second and not loss and not conflicts and not more_conflicts
    assert first["alpha"] == rows["alpha"]


def test_slot_selection_preserves_other_records_and_edits_only_that_slot(source):
    op = choose(keep=[{"kind": "Alpha", "slots": ["title"]}, {"kind": "Beta"}],
                omit=[{"kind": "Alpha", "slot": "size", "reason": "The value is not used"}])
    m = operate.model(source)
    step = selection.SelectOp(m, op)
    edits = operate.Edits()
    step.schema(edits)
    step.facts(None, edits)
    schema = yaml.safe_load(edits.apply("schema/minimal.yaml", operate.read_text(source / "schema/minimal.yaml")))
    assert "size" not in schema["classes"]["Alpha"]["attributes"]
    after = yaml.safe_load(edits.apply("facts/data.yaml", operate.read_text(source / "facts/data.yaml")))
    assert after["alpha"] == [{"id": "a", "title": "First"}]
    assert after["beta"] == [{"id": "b", "alpha": "a", "state": "low"}]


@pytest.mark.parametrize("change,message", [
    ({"omit": []}, "omission reason for kinds"),
    ({"keep": [{"kind": "Alpha", "slots": ["title"]}]}, "omission reason for slots"),
    ({"keep": [{"kind": "Alpha"}, {"kind": "Alpha"}]}, "repeats kind"),
    ({"keep": [{"kind": "Beta"}], "omit": [{"kind": "Alpha", "reason": "Excluded"}]}, "stays and has alpha"),
    ({"keep": [{"kind": "Alpha"}, {"kind": "Beta"}]}, "both keep and omit a kind"),
    ({"omit": [{"kind": "Beta", "reason": "Excluded"}, {"kind": "Alpha", "slot": "id", "reason": "Excluded"}]}, "identifier"),
])
def test_incomplete_or_structurally_invalid_selections_block_before_edits(source, change, message):
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    with pytest.raises(operate.OperationError, match=message):
        selection.SelectOp(operate.model(source), choose(**change))
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("change", [{"accept_loss": False}, {"keep": []}, {"keep": "Alpha"},
                                   {"omit": [{"kind": "Beta"}]}, {"omit": [{"kind": "Beta", "reason": "  "}]},
                                   {"omit": [{"kind": "Beta", "reason": "Excluded", "extra": True}]},
                                   {"keep": [{"kind": "Alpha", "slots": "title"}]}, {"kind": "Alpha"}])
def test_select_file_shape_is_strict(tmp_path, change):
    f = tmp_path / "operations.yaml"
    f.write_text(yaml.safe_dump({"format": operate.FORMAT, "pack": "minimal", "operations": [choose(**change)]}))
    with pytest.raises(operate.OperationError):
        operate.load(f)


def test_select_fields_are_not_silently_accepted_by_other_operations(tmp_path):
    f = tmp_path / "operations.yaml"
    f.write_text(yaml.safe_dump({"format": operate.FORMAT, "pack": "minimal", "operations": [
        {"op": "rename", "kind": "Alpha", "to": "Other", "keep": [{"kind": "Beta"}]}]}))
    with pytest.raises(operate.OperationError, match="takes no 'keep'"):
        operate.load(f)


def test_simultaneous_omission_can_remove_a_cycle_without_an_invalid_intermediate_schema(source):
    f = source / "schema/minimal.yaml"
    schema = yaml.safe_load(f.read_text())
    schema["classes"]["Beta"]["attributes"]["peer"] = {"range": "Gamma"}
    schema["classes"]["Gamma"] = {"attributes": {"id": {"identifier": True}, "peer": {"range": "Beta"}}}
    f.write_text(yaml.safe_dump(schema))
    op = choose(omit=[{"kind": "Beta", "reason": "Excluded"}, {"kind": "Gamma", "reason": "Excluded"}])
    step = selection.SelectOp(operate.model(source), op)
    assert step.gone_tables == {"beta", "beta__alpha", "beta__state", "beta__peer", "gamma", "gamma__peer"}
    edits = operate.Edits()
    step.schema(edits)
    after = yaml.safe_load(edits.apply("schema/minimal.yaml", operate.read_text(f)))
    assert set(after["classes"]) == {"Alpha"}


def test_an_omitted_owning_slot_removes_its_child_rows_while_the_selected_type_stays(source):
    f = source / "schema/minimal.yaml"
    schema = yaml.safe_load(f.read_text())
    schema["classes"]["Alpha"]["attributes"]["parts"] = {"range": "Part", "multivalued": True, "inlined_as_list": True}
    schema["classes"]["Alpha"]["attributes"]["retained_parts"] = {"range": "Part", "multivalued": True, "inlined_as_list": True}
    schema["classes"]["Part"] = {"attributes": {"value": {}}}
    f.write_text(yaml.safe_dump(schema))
    f = source / "facts/data.yaml"
    data = yaml.safe_load(f.read_text())
    data["alpha"][0]["parts"] = [{"value": "Inside"}]
    f.write_text(yaml.safe_dump(data))
    op = choose(keep=[{"kind": "Alpha", "slots": ["title", "size", "retained_parts"]}, {"kind": "Beta"}, {"kind": "Part"}],
                omit=[{"kind": "Alpha", "slot": "parts", "reason": "Outside the core"}])
    m = operate.model(source)
    step = selection.SelectOp(m, op)
    p = step.plan(None)
    rows, lost, conflicts = evaluate(p.forward, p.gone, facts.load(m.pack, f))
    assert not conflicts and "part" not in step.d.kinds
    assert "part" not in rows and "part__value" not in rows
    assert set(lost) == {"alpha__parts", "part", "part__value"}


def test_refactored_drop_keeps_its_existing_structural_boundary(source):
    m = operate.model(source)
    assert operate.plan_drop(m, {"kind": "Beta"}).tables == {"beta", "beta__alpha", "beta__state"}
    with pytest.raises(operate.OperationError, match="drop Alpha.*stays and has alpha"):
        operate.plan_drop(m, {"kind": "Alpha"})
