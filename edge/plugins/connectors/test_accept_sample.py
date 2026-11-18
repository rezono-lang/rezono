"""Accepted rows and explicitly refused versioned rows exercise different outcomes."""

import accept
from acceptance_sample import AT, PIN, fixture, objects


def test_a_one_row_parcel_is_accepted_by_each_real_reader():
    schema, rows = fixture()
    result = accept.accept(schema, rows, PIN)
    assert {name: check["state"] for name, check in result.items()} == dict.fromkeys(
        ("rdf", "shacl", "odcs", "dcat"), "accepted")
    published = accept.published(objects(), AT)
    for name in ("view.ttl", "prov.ttl", "shapes.ttl", "contract.odcs.yaml", "dcat.ttl"):
        assert published[name]["state"] == "accepted", published[name]


def test_versioned_rows_name_the_rdf_refusal_and_other_readers_still_run():
    schema, rows = fixture()
    schema["kinds"]["Parcel"]["versioned"] = {"at": "Date", "known": "Date"}
    rows[0].update({"$valid": {"at": "2026-01-01.."}, "$known": "2026-01-01"})
    result = accept.accept(schema, rows, PIN)
    for name in ("rdf", "shacl"):
        assert result[name]["state"] == "refused" and "Q13" in result[name]["detail"]
    for name in ("odcs", "dcat"):
        assert result[name]["state"] == "accepted", result[name]
