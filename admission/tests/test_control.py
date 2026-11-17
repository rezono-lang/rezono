"""DV1: decided values (`plane: control`) enter only from a reviewed proposal, and each names its decision. On a
small bundle of admission's own: no compiler."""

from __future__ import annotations

from rezono_admission import Admission, Schema, rows

BUNDLE = {
    "format": "rezono.schema-bundle/1",
    "pack": {"id": "t", "version": "1", "default_language": "en"},
    "kinds": [{"id": "rate", "identifier": "id", "id_type": "text", "plane": "control", "owner": "board"},
              {"id": "special_rate", "parent": "rate", "id_type": "text"},
              {"id": "case", "identifier": "id", "id_type": "text"}],
    "attributes": [{"id": "rate.decision", "kind": "rate", "name": "decision", "table": "rate__decision",
                    "type": "text"},
                   {"id": "rate.value", "kind": "rate", "name": "value", "table": "rate__value", "type": "integer"},
                   {"id": "case.size", "kind": "case", "name": "size", "table": "case__size", "type": "integer"}],
}


def test_a_decided_value_names_its_decision():
    schema = Schema(BUNDLE)
    assert schema.control("rate") and schema.control("special_rate"), "a subkind of a control kind is one too"
    assert not schema.control("case")
    got, refusals = rows(schema, {"rate": [{"id": "r1", "value": 3, "decision": "d-1"}, {"id": "r2", "value": 4},
                                           {"id": "r3", "decision": ""}],
                                  "special_rate": [{"id": "s1", "value": 5}],
                                  "case": [{"id": "c1", "size": 1}]})
    assert [(r.code, r.where) for r in refusals] == [
        ("decision_missing", "rate[2].decision"), ("decision_missing", "rate[3].decision"),
        ("decision_missing", "special_rate[1].decision")]
    assert got == {"case": [("c1",)], "case__size": [("c1", 1)], "rate": [("r1",)],
                   "rate__decision": [("r1", "d-1")], "rate__value": [("r1", 3)]}


def test_a_decided_value_has_exactly_one_decision_and_it_is_not_empty():
    # REVIEW-ENGINE-B on #799: a list is unwrapped for a single-valued slot, so the rows are judged, not the text.
    got, refusals = rows(Schema(BUNDLE), {"rate": [{"id": "r1", "decision": [""]}, {"id": "r2", "decision": ["a", "b"]},
                                                   {"id": "r3", "decision": ["d-3"]}, {"id": "r4", "decision": []}]})
    assert [(r.code, r.where) for r in refusals] == [
        ("decision_missing", "rate[1].decision"), ("decision_missing", "rate[2].decision"),
        ("decision_missing", "rate[4].decision")]
    assert got["rate__decision"] == [("r3", "d-3")]
    assert rows(Schema(BUNDLE), {"rate": []}) == ({}, []), "an empty section is admitted and gives no row"


def test_a_direct_delta_on_a_control_kind_is_refused_with_its_reason():
    a = Admission(Schema(BUNDLE))
    delta = {"rate": [{"id": "r1", "value": 3, "decision": "d-1"}], "case": [{"id": "c1", "size": 1}]}
    refused = a.admit(delta, source="feed", event="e1")
    assert [(r.code, r.where) for r in refused.refusals] == [("control_unreviewed", "rate")]
    assert refused.rows == {} and not refused.admitted, "a batch is all or nothing"
    sub = a.admit({"special_rate": [{"id": "s1", "value": 5, "decision": "d-2"}]}, source="feed", event="e2")
    assert [(r.code, r.where) for r in sub.refusals] == [("control_unreviewed", "rate"),
                                                          ("control_unreviewed", "special_rate")]
    assert a.admit({"case": [{"id": "c1", "size": 1}]}, source="feed", event="e3").admitted, \
        "a data-plane delta needs no review"
    reviewed = a.admit(delta, source="git", event="e4", reviewed="proposal-17")
    assert reviewed.admitted and reviewed.rows["rate__decision"] == [("r1", "d-1")]
    unnamed = a.admit({"rate": [{"id": "r2", "value": 4}]}, source="git", event="e5", reviewed="proposal-17")
    assert [r.code for r in unnamed.refusals] == ["decision_missing"], "a review does not excuse a missing decision"
