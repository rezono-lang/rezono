"""A hand-counted ODCS example with a bounded quantity and nullable state."""

import json
from pathlib import Path

import duckdb
import jsonschema
import open_data_contract_standard
import yaml

import odcs
from rezono_publication import arrow


HERE = Path(__file__).parent


def test_official_contract_and_quality_counts_over_arrow():
    schema = {"rezono": "1.0", "base": "https://example.org/parcels/", "pack": "parcels",
              "types": {"Kg": {"of": "Quantity", "dimension": "mass", "unit": "kg",
                               "storage_unit": "g", "factor": "1000", "storage": "int64",
                               "min": "1", "max": "2"}},
              "kinds": {"Parcel": {"id": {"type": "Text"}, "world": "closed", "slots": {
                  "mass": {"type": "Kg", "card": "1", "states": ["known", "unknown"]}}}}}
    rows = [{"$kind": "Parcel", "$id": "blue", "mass": "1 kg"},
            {"$kind": "Parcel", "$id": "grey", "mass": {"$unknown": ""}}]
    official = Path(open_data_contract_standard.__file__).with_name("schema.json")
    doc = yaml.safe_load(odcs.to_yaml(schema))
    jsonschema.Draft201909Validator(json.loads(official.read_text("utf-8"))).validate(doc)
    parcel, = [t for t in doc["schema"] if t["name"] == "Parcel"]
    columns = {p["name"]: p for p in parcel["properties"]}
    mass = columns["mass"]
    assert doc["apiVersion"] == "v3.2.0" and mass["physicalType"] == "int64"
    custom = {prop["property"]: prop["value"] for prop in mass["customProperties"]}
    assert custom["rezonoExtension"]["metadata"]["unit"] == "kg"
    assert custom["rezonoExtension"]["metadata"]["factor"] == "1000"
    losses = yaml.safe_load((HERE / "odcs.losses.yaml").read_text("utf-8"))
    carriers = {item["subject"]: item["carried_by"] for item in losses["losses"] if item["fate"] == "extension"}
    for subject, prop in [("unit", "rezonoExtension"), ("state", "rezonoField"), ("world", "rezonoWorld"),
                          ("source", "rezonoTable"), ("proof", "rezonoTable")]:
        assert "customProperties." + prop in carriers[subject]
    table_properties = {p["property"]: p["value"] for p in parcel["customProperties"]}
    assert table_properties["rezonoWorld"] == "closed"
    assert columns["mass$state"]["physicalType"] == "int8"
    for name in ("$src", "$why"):
        side, = [item for item in doc["schema"] if item["name"] == name]
        metadata, = [p["value"] for p in side["customProperties"] if p["property"] == "rezonoTable"]
        assert metadata["table"] == name
    checks = {r["id"]: r for r in mass["quality"]}
    assert all(checks[k]["mustBe"] == 0 for k in ("bounds", "null-beside-state"))
    table = arrow.to_arrow(schema, rows)["Parcel"]
    with duckdb.connect() as db:
        db.register("original_rows", table)
        db.execute('CREATE TABLE "Parcel" AS SELECT * FROM original_rows')
        # 1 kg = 1000 g. Unknown mass has the state code 2 and no stored value.
        assert db.execute('SELECT mass, "mass$state" FROM "Parcel" ORDER BY "$id"').fetchall() == [(1000, 0), (None, 2)]

        def counts():
            return tuple(db.execute(checks[key]["query"]).fetchone()[0] for key in ("bounds", "null-beside-state"))

        assert counts() == (0, 0)
        db.execute('UPDATE "Parcel" SET mass=2001 WHERE "$id"=\'blue\'')
        assert counts() == (1, 0)
        db.execute('UPDATE "Parcel" SET mass=1000 WHERE "$id"=\'grey\'')
        assert counts() == (1, 1)
