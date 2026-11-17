"""DV1: a pack says which kinds hold decided values (`plane: control`, decision O13; Reckon Data L0 §3.7). The
compiler reads the marker and its owner, refuses a control kind that cannot name its decision, writes both into
the schema bundle, and its loader refuses a decided value without its decision. A kind that says nothing is a
data-plane kind and its bundle entry is unchanged."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import emit, facts, pack

from support import FIXTURE


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def schema_with(d: Path, edit) -> Path:
    f = d / "schema" / "minimal.yaml"
    s = yaml.safe_load(f.read_text(encoding="utf-8"))
    edit(s)
    f.write_text(yaml.safe_dump(s, sort_keys=False), encoding="utf-8")
    return d


def control(cls: str, decision: dict | None, **notes):
    def edit(s):
        c = s["classes"][cls]
        c["annotations"] = {"plane": "control", "owner": "board"} | notes
        if decision is not None:
            c["attributes"]["decision"] = decision
    return edit


def bundle(model) -> dict:
    return json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])


def test_a_control_kind_is_in_the_bundle_and_its_values_name_their_decision(fixture):
    model = pack.read(schema_with(fixture, control("Alpha", {"required": True})))
    kinds = {k["id"]: k for k in bundle(model)["kinds"]}
    assert (kinds["alpha"]["plane"], kinds["alpha"]["owner"]) == ("control", "board")
    assert "plane" not in kinds["beta"] and "owner" not in kinds["beta"], "a data-plane kind says nothing"
    assert facts.schema(model).control("alpha") and not facts.schema(model).control("beta")
    assert facts.rows_of(model, {"alpha": [{"id": "a", "title": "t", "decision": "d-1"}]})["alpha__decision"] == [
        ("a", "d-1")]
    with pytest.raises(facts.LoadError, match=r"alpha\[1\]\.decision: a decided value names its decision"):
        facts.rows_of(model, {"alpha": [{"id": "a", "title": "t"}]})
    with pytest.raises(facts.LoadError, match=r"alpha\[1\]\.decision: a decided value names its decision"):
        facts.rows_of(model, {"alpha": [{"id": "a", "title": "t", "decision": ""}]})
    assert facts.rows_of(model, {"beta": [{"id": "b", "alpha": "a"}]}), "a data-plane record needs no decision"


def test_a_decision_may_be_an_arrow(fixture):
    model = pack.read(schema_with(fixture, control("Beta", {"range": "Alpha", "required": True})))
    assert facts.schema(model).control("beta")


def test_an_unmarked_pack_has_no_plane_in_its_bundle():
    assert not [k for k in bundle(pack.read(FIXTURE))["kinds"] if "plane" in k or "owner" in k]


REFUSED = {
    "data": (control("Alpha", {"required": True}, plane="data"), "plane is only ever control"),
    "no-owner": (control("Alpha", {"required": True}, owner=""), "names its owner"),
    "owner-alone": (lambda s: s["classes"]["Alpha"].update(annotations={"owner": "board"}),
                    "owner is said of a control kind only"),
    "no-decision": (control("Alpha", None), "required, single-valued slot decision"),
    "optional": (control("Alpha", {}), "required, single-valued slot decision"),
    "many": (control("Alpha", {"required": True, "multivalued": True}), "required, single-valued slot decision"),
    "enum": (control("Alpha", {"required": True, "range": "State"}), "required, single-valued slot decision"),
    "number": (control("Alpha", {"required": True, "range": "integer"}), "required, single-valued slot decision"),
    # REVIEW-ENGINE-B on #799: below a data-plane parent it would share the parent's tables, unreviewed.
    "below-data": (lambda s: s["classes"].update(Gamma={"is_a": "Alpha", "annotations": {
        "plane": "control", "owner": "board"}, "attributes": {"decision": {"required": True}}}),
        "not below a data-plane kind"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_a_control_kind_is_refused_when_it_cannot_name_its_decision(fixture, case):
    edit, message = REFUSED[case]
    with pytest.raises(pack.CompileError, match=message):
        pack.read(schema_with(fixture, edit))
