"""A one-row publication whose inputs and role index are known to the test."""

import json

from rezono_publication import l0
from rezono_publisher import forms


AT = "https://example.org/publications/parcels/m-7/reader/"
PIN = {"manifest": "m-7", "dataset": "d-" + "a" * 64}


def fixture():
    schema = {"rezono": "1.0", "base": "https://example.org/parcels/", "pack": "parcels",
              "kinds": {"Parcel": {"id": {"type": "Text"}, "world": "closed", "slots": {}}}}
    return schema, [{"$kind": "Parcel", "$id": "blue"}]


def objects():
    schema, rows = fixture()
    out = forms.exports(schema, rows, PIN["dataset"], PIN["manifest"], [])
    out["schema.json"] = json.dumps(schema).encode()
    out["rows.json"] = json.dumps({"$schema": l0.schema_id(schema), "$rows": rows}).encode()
    out["index.json"] = json.dumps({"dataset": PIN["dataset"], "manifest": {"id": PIN["manifest"]},
                                    "objects": [{"name": name} for name in sorted(out)]}).encode()
    return out
