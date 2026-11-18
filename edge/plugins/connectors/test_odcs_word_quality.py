"""A valid Unicode word must pass the exported quality rule in the ODCS reader."""

import duckdb
import pytest

import odcs
from rezono_publication import arrow


@pytest.mark.xfail(strict=True, reason="Preserve Unicode word matching in ODCS quality rules in edge/plugins/connectors/odcs.py. Read decisions/odcs-quality-coverage.md.")
def test_unicode_word_rule_agrees_with_the_publication_reader():
    schema = {"rezono": "1.0", "base": "https://example.org/labels/", "pack": "labels",
              "types": {"Word": {"of": "Text", "pattern": r"\w+"}},
              "kinds": {"Tag": {"id": {"type": "Text"}, "world": "closed", "slots": {
                  "label": {"type": "Word", "card": "1", "states": ["known"]}}}}}
    rows = [{"$kind": "Tag", "$id": "a", "label": "caf\u00e9"}, {"$kind": "Tag", "$id": "b", "label": "plain_2"}]
    table = arrow.to_arrow(schema, rows)["Tag"]
    obj, = [t for t in odcs.contract(schema)["schema"] if t["name"] == "Tag"]
    prop, = [p for p in obj["properties"] if p["name"] == "label"]
    rule, = [r for r in prop["quality"] if r.get("metric") == "invalidValues"]
    regex = rule["arguments"]["pattern"]
    with duckdb.connect() as db:
        db.register("tags", table)
        assert db.execute("SELECT label FROM tags WHERE NOT regexp_matches(label, ?)", [regex]).fetchall() == []
        assert db.execute("SELECT regexp_matches(?, ?)", ["bad!", regex]).fetchone() == (False,)
