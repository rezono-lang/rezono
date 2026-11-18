"""Check derived publication types against a supplied pinned bundle."""

from copy import deepcopy

import pytest

from rezono_canon import canonical_json, sha256_hex
from rezono_checker.check import check_epoch
from rezono_checker.rules import load_rules
from rezono_publication import l0, publication
from rezono_publication.hash import hashes
from rezono_publisher import access, forms, publish


class UntypedDerivedColumn(AssertionError):
    """The schema generator discards a checked logical column type."""


def bundle():
    return {
        "format": "rezono.schema-bundle/1",
        "pack": {"id": "example", "version": "1", "default_language": "en"},
        "imports": [],
        "schemas": [{"id": "https://example.org/example/stages", "name": "stages",
                     "file": "schema/stages.yaml", "module": "stages", "pack": "example"}],
        "layers": ["facts"],
        "order": ["stage"],
        "kinds": [{
            "id": "stage", "stable_id": "https://example.org/example/stages#Stage",
            "span": {"file": "schema/stages.yaml", "line": "4", "column": "3"},
            "class": "Stage", "layer": "facts", "abstract": False, "identifier": "id",
            "id_type": "text", "module": "stages", "table": "stage", "world": "closed",
        }],
        "relations": [{"id": "ranked_stage", "module": "counts", "explain": "materialize",
                       "world": "closed", "columns": [
                           {"name": "stage", "type": "string",
                            "semantic": {"case": "ref", "base": "string", "target": "stage"}},
                           {"name": "count", "type": "integer"},
                           {"name": "label", "type": "string"},
                       ]}],
    }


def withheld_form(compiled, manifest, results):
    columns = {"stage": ("stage",), "may_read": (None, None, None),
               "private_input": ("private_origin", "stage", None, None)}
    inputs = [("hidden", *result) for result in results]
    terms = ["?origin", "?stage", "?count", "?label"]
    rule = {"id": "rank", "stratum": "0", "head": {"relation": "ranked_stage", "terms": terms[1:]},
            "body": [{"relation": "private_input", "terms": terms, "polarity": "positive", "stratum": "0"}]}
    ir = {"rules": [rule], "relations": [
        {"name": "ranked_stage", "role": "derived", "key": compiled["relations"][0]["columns"]},
    ]}
    rows = {"stage": [("stage-a",)], "may_read": [("consumer", "stage", "stage-a")],
            "private_input": inputs, "ranked_stage": results}
    witnesses = [{"rule_id": "rank",
                  "bindings": [{"variable": name, "value": value} for name, value in zip(terms, premise)],
                  "conclusion": {"relation": "ranked_stage", "key": canonical_json(result)},
                  "premises": [{"row": {"relation": "private_input", "key": canonical_json(premise)},
                                "polarity": "positive", "stratum": 0}]}
                 for premise, result in zip(inputs, results)]
    snapshots = {relation: publish.snapshot(values) for relation, values in rows.items()}
    archive = {"id": manifest["id"], "snapshots": [
        {"relation": name, "uri": name, "sha256": sha256_hex(data), "format": "json", "role": "checker",
         "complete": True} for name, data in snapshots.items()
    ]}
    assert check_epoch(witnesses, archive, load_rules(ir), snapshots.__getitem__, derived={"ranked_stage"})["valid"]
    readable, proofs, full = access.for_role(rows, {"stage", "private_origin"}, {}, columns, ir, witnesses, "consumer")
    assert readable["private_input"] == readable["ranked_stage"] == proofs["witnesses"] == []
    assert "ranked_stage" not in full
    role_form = publication.form(manifest, compiled, readable, full, proofs["witnesses"], [], "consumer")
    role_objects = forms.objects(role_form)
    _, back = forms.verify(role_objects, role_form, readable, compiled, full)
    assert back["rows"] == [{"$kind": "Stage", "$id": "stage-a"}]
    return role_objects, back["schema"]["kinds"]["RankedStage"]


@pytest.mark.xfail(strict=True, raises=UntypedDerivedColumn,
                   reason="Publish checked semantic columns and retain the ordered snapshot key.")
def test_publication_derived_column_types():
    compiled = bundle()
    expected = ("stage-a", "9007199254740993", "001")
    given = {"stage": [("stage-a",)], "ranked_stage": [expected]}
    manifest = {"id": "m-1", "epoch": 1, "knowledge_time": "2026-01-01T00:00:00Z"}
    narrow, narrow_kind = withheld_form(compiled, manifest, [expected])
    assert withheld_form(compiled, manifest, [expected, ("stage-a", "19", "withheld")]) == (narrow, narrow_kind)
    form = publication.form(manifest, compiled, given, None, [], [], "checker")
    rank = form["schema"]["kinds"]["RankedStage"]
    if rank["slots"]["stage"].get("type") == "Text":
        raise UntypedDerivedColumn("the checked Stage reference was published as Text")
    assert rank["tuple_key"] == ["stage", "count", "label"]
    assert narrow_kind["tuple_key"] == rank["tuple_key"]
    assert rank["slots"]["stage"]["ref"] == "Stage"
    assert rank["slots"]["count"]["type"] == "Integer"
    assert rank["slots"]["label"]["type"] == "Text"
    _, back = forms.verify(forms.objects(form), form, given, compiled, None)
    assert back["rows"] == [
        {"$kind": "RankedStage", "$id": '["stage-a","9007199254740993","001"]',
         "stage": {"$ref": "stage-a"}, "count": "9007199254740993", "label": "001"},
        {"$kind": "Stage", "$id": "stage-a"},
    ]

    stripped = deepcopy(form["schema"])
    del stripped["kinds"]["RankedStage"]["tuple_key"]
    rehashed = form | {"schema": stripped, "hashes": hashes(stripped, form["rows"])}
    with pytest.raises(forms.Blocked, match=r"tuple_key|schema.*(?:definition|bundle)"):
        forms.verify(forms.objects(rehashed), rehashed, given, compiled, None)

    physical = deepcopy(compiled)
    del physical["relations"][0]["columns"][0]["semantic"]
    legacy, _ = publication.schema_document(physical)
    l0.check_schema(legacy)
    assert [legacy["kinds"]["RankedStage"]["slots"][name]["type"] for name in rank["tuple_key"]] == [
        "Text", "Integer", "Text",
    ]

    for bad in ("unknown-target", "wrong-storage"):
        corrupt = deepcopy(compiled)
        column = corrupt["relations"][0]["columns"][0]
        if bad == "unknown-target":
            column["semantic"]["target"] = "other-stage"
        else:
            column["type"] = "integer"
        with pytest.raises(publication.FormError):
            publication.schema_document(corrupt)
