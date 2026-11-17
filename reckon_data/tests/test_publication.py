"""A role's form of a definition with a kind tree (RV-K26; docs/reckon-data/l0.md §2.1 `parent`, §3.1).

The fixture is neutral and hand-made (`subkind_fixture`): no compiler and no engine. Each form is read by the
library's reader, hashed, and held against the role's own rows, as the publisher does before it writes one
(rezono_publisher.forms.verify).
"""

import copy

import pytest

from reckon_data import l0, publication
from reckon_data.hash import hashes
from reckon_data.tests.subkind_fixture import BUNDLE, NARROW, SOURCE_A, SOURCE_B, WIDE

UNREAD = {"$unknown": publication.NOT_READ_IN_FULL}


def form_of(role: dict, bundle: dict = BUNDLE, full="role"):
    full = role["full"] if full == "role" else full
    doc, plan = publication.schema_document(bundle, full)
    rows = publication.row_json(doc, plan, {"rows": role["rows"], "witnesses": [], "sources": role["sources"]})
    l0.check_schema(doc)
    l0.read_rows(doc, rows)
    return doc, plan, rows


def by_id(rows):
    return {r["$id"]: r for r in rows if not r["$id"].startswith("[")}


def test_a_subkind_names_its_parent_and_restates_its_slots():
    doc, plan, _ = form_of(WIDE, full=None)
    kinds = doc["kinds"]
    assert [kinds[k].get("parent") for k in ("Item", "Part", "Spare", "Tool", "Holder")] == [
        None, "Item", "Part", "Item", None]
    assert set(kinds["Item"]["slots"]) == set(kinds["Tool"]["slots"]) == {"label", "inside"}
    assert set(kinds["Part"]["slots"]) == set(kinds["Spare"]["slots"]) == {"label", "inside", "size"}
    for name in ("Part", "Spare", "Tool"):
        assert kinds[name]["slots"]["label"] == kinds["Item"]["slots"]["label"]
    assert kinds["Holder"]["slots"]["keeps"]["ref"] == "Item"  # a reference names the kind the schema names
    assert plan["family"]["Item"] == ["Item", "Part", "Spare", "Tool"] and plan["family"]["Holder"] == ["Holder"]


def test_an_element_is_written_once_at_its_most_specific_kind_with_every_slot():
    doc, plan, rows = form_of(WIDE, full=None)
    elements = by_id(rows)
    assert {i: r["$kind"] for i, r in elements.items()} == {
        "i1": "Item", "p1": "Part", "p2": "Part", "s1": "Spare", "t1": "Tool", "h1": "Holder"}
    assert len(rows) == len(elements) + 2  # and the two derived rows; no element twice
    assert elements["s1"] == {"$kind": "Spare", "$id": "s1", "label": "washer", "size": "1", "inside": {"$ref": "p1"},
                              "$src": {"label": [SOURCE_A]}}
    assert elements["p2"] == {"$kind": "Part", "$id": "p2", "label": "bolt", "size": {"$na": ""},
                              "inside": {"$ref": "p1"}}
    assert elements["i1"] == {"$kind": "Item", "$id": "i1", "label": "crate", "inside": {"$na": ""}}
    # A reference to the parent kind points at an element of a subkind by the same id.
    assert elements["h1"]["keeps"] == [{"$ref": "i1"}, {"$ref": "p1"}, {"$ref": "s1"}]
    # The sources of the element's row in each kind of its chain are the sources of the one element.
    assert elements["p1"]["$src"] == {"$id": [SOURCE_A, SOURCE_B]}
    assert publication.differences(doc, plan, rows, WIDE["rows"]) == []


def test_the_form_maps_back_onto_every_table_of_the_chain():
    doc, plan, rows = form_of(WIDE)
    back = publication.relations(doc, plan, rows)
    assert back == publication.expected_relations(doc, plan, WIDE["rows"])
    assert back["item"] == {'["i1"]', '["p1"]', '["p2"]', '["s1"]', '["t1"]'}
    assert back["part"] == {'["p1"]', '["p2"]', '["s1"]'} and back["spare"] == {'["s1"]'}
    assert back["item__label"] >= {'["s1","washer"]', '["i1","crate"]'}


def test_a_role_that_reads_the_subkind_only_gets_the_slots_above_as_not_read_in_full():
    """O7: a right on `part` holds for `spare`, not for `item`. The role's files hold `p1` as a part and nothing
    of `item`; the form writes the part with the item's slots as any slot the role does not read in full (O8),
    and names no element and no value the role's files do not hold."""
    doc, plan, rows = form_of(NARROW)
    kinds = doc["kinds"]
    assert kinds["Item"]["world"] == "open" and kinds["Part"]["world"] == kinds["Spare"]["world"] == "closed"
    assert kinds["Part"]["slots"]["label"] == {"type": "Text", "card": "1", "states": ["known", "unknown"],
                                               "world": "open"}
    assert kinds["Item"]["slots"]["label"] == {"type": "Text", "card": "1", "states": ["known", "unknown"]}
    assert kinds["Part"]["slots"]["inside"]["states"] == ["known", "not_applicable", "unknown"]
    assert "world" not in kinds["Part"]["slots"]["size"]
    assert rows == [
        {"$kind": "Part", "$id": "p1", "label": UNREAD, "inside": UNREAD, "size": "3",
         "$src": {"$id": [SOURCE_A, SOURCE_B]}},
        {"$kind": "Part", "$id": "p2", "label": UNREAD, "inside": UNREAD, "size": {"$na": ""}},
        {"$kind": "Spare", "$id": "s1", "label": UNREAD, "inside": UNREAD, "size": "1"},
    ]
    assert publication.differences(doc, plan, rows, NARROW["rows"]) == []
    assert hashes(doc, rows)["tables"]["Item"] == hashes(doc, [])["tables"]["Item"]  # no row of the parent's table


def test_the_role_s_schema_depends_on_no_row():
    """`full` follows from the read rules, so two worlds that differ in rows give the same schema document."""
    emptied = {**NARROW, "rows": {t: [] for t in NARROW["rows"]}, "sources": []}
    assert form_of(NARROW)[0] == form_of(emptied)[0]


@pytest.mark.parametrize("edit, says", [
    (lambda rows: [r for r in rows if r["$id"] != "s1"], "spare: [\"s1\"] is in the role's files, not in the form"),
    (lambda rows: [dict(r, **{"$kind": "Part"}) if r["$id"] == "s1" else r for r in rows],
     "spare: [\"s1\"] is in the role's files, not in the form"),
    (lambda rows: [dict(r, **{"$kind": "Spare"}) if r["$id"] == "p2" else r for r in rows],
     "spare: [\"p2\"] is in the form, not in the role's files"),
    (lambda rows: [dict(r, label="hinge") if r["$id"] == "p1" else r for r in rows],
     "item__label: [\"p1\",\"hinge\"] is in the form, not in the role's files"),
], ids=["an element left out", "written at its parent", "written at a kind below", "a value of a kind above"])
def test_a_form_that_says_other_than_the_role_s_files_is_named(edit, says):
    doc, plan, rows = form_of(NARROW)
    assert says in publication.differences(doc, plan, edit(copy.deepcopy(rows)), NARROW["rows"])


def test_one_id_in_two_kinds_with_neither_above_the_other_is_refused():
    rows = {**WIDE["rows"], "tool": [("t1",), ("p1",)]}
    with pytest.raises(publication.FormError, match="p1 is an element of (Part|Tool) and of (Part|Tool)"):
        form_of({**WIDE, "rows": rows})


def test_a_value_of_an_element_the_role_does_not_read_as_that_kind_is_refused():
    rows = {**WIDE["rows"], "part__size": [("i1", "9")]}  # i1 is an item, no part
    with pytest.raises(publication.FormError, match="part__size: i1 is not an element of Part"):
        form_of({**WIDE, "rows": rows})


def test_a_parent_chain_that_does_not_end_is_refused():
    bundle = copy.deepcopy(BUNDLE)
    bundle["kinds"][0]["parent"] = "spare"
    with pytest.raises(publication.FormError, match="do not end at a root kind"):
        publication.schema_document(bundle)


def test_two_slots_whose_types_would_share_a_name_and_differ_get_no_form():
    """A type is named after its slot's schema type; two inline patterns on a plain string would be one type."""
    bundle = copy.deepcopy(BUNDLE)
    for name, pattern in (("code", "^[a-z]+$"), ("mark", "^[0-9]+$")):
        bundle["attributes"].append({"id": f"holder.{name}", "kind": "holder", "name": name, "type": "text",
                                     "table": f"holder__{name}", "schema_type": "string", "patterns": [pattern],
                                     "required": False, "multivalued": False, "world": "closed"})
    with pytest.raises(publication.FormError, match="holder.mark: a second type named String"):
        publication.schema_document(bundle)
    bundle["attributes"][-1]["patterns"] = ["^[a-z]+$"]  # the same type twice is one type
    assert publication.schema_document(bundle)[0]["types"]["String"] == {"of": "Text", "pattern": "^[a-z]+$"}


def test_a_control_kind_s_subkinds_are_control_kinds_with_the_decision_they_restate():
    bundle = copy.deepcopy(BUNDLE)
    bundle["kinds"][0] |= {"plane": "control", "owner": "stewards"}
    bundle["attributes"].append({"id": "item.decision", "kind": "item", "name": "decision", "table": "item__decision",
                                 "type": "text", "required": True, "multivalued": False, "world": "closed"})
    doc, _ = publication.schema_document(bundle)
    l0.check_schema(doc)
    for name in ("Item", "Part", "Spare", "Tool"):
        assert doc["kinds"][name]["plane"] == "control" and doc["kinds"][name]["owner"] == "stewards"
        assert doc["kinds"][name]["slots"]["decision"]["states"] == ["known"]
    # A role that reads the decision in part gets none of them as a control kind (§3.7).
    partial, _ = publication.schema_document(bundle, {"item", "part", "spare", "tool"})
    l0.check_schema(partial)
    assert not any("plane" in k for k in partial["kinds"].values())


def test_a_definition_without_a_subkind_has_no_parent_and_one_kind_per_family():
    bundle = {**BUNDLE, "kinds": [{k: v for k, v in kind.items() if k != "parent"} for kind in BUNDLE["kinds"]],
              "attributes": BUNDLE["attributes"][:1]}
    doc, plan = publication.schema_document(bundle)
    assert not any("parent" in k for k in doc["kinds"].values())
    assert all(family == [name] for name, family in plan["family"].items())
    assert set(doc["kinds"]["Part"]["slots"]) == set()
