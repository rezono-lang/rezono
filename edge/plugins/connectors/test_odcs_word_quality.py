"""Unicode word patterns agree in the publication reader and the exported quality rule."""

import duckdb
import pytest

import odcs
from rezono_publication import arrow, l0


def _word_schema(pattern):
    return {"rezono": "1.0", "base": "https://example.org/labels/", "pack": "labels",
            "types": {"Word": {"of": "Text", "pattern": pattern}},
            "kinds": {"Tag": {"id": {"type": "Text"}, "world": "closed", "slots": {
                "label": {"type": "Word", "card": "1", "states": ["known"]}}}}}


def _exported_pattern(schema):
    obj, = [t for t in odcs.contract(schema)["schema"] if t["name"] == "Tag"]
    prop, = [p for p in obj["properties"] if p["name"] == "label"]
    rule, = [r for r in prop["quality"] if r.get("metric") == "invalidValues"]
    return rule["arguments"]["pattern"]


def test_unicode_word_rule_agrees_with_the_publication_reader():
    schema = _word_schema(r"\w+")
    rows = [{"$kind": "Tag", "$id": "a", "label": "caf\u00e9"}, {"$kind": "Tag", "$id": "b", "label": "plain_2"}]
    table = arrow.to_arrow(schema, rows)["Tag"]
    regex = _exported_pattern(schema)
    assert regex == r"^(?:[\p{L}\p{N}_]+)$"
    with duckdb.connect() as db:
        db.register("tags", table)
        assert db.execute("SELECT label FROM tags WHERE NOT regexp_matches(label, ?)", [regex]).fetchall() == []
        assert db.execute("SELECT regexp_matches(?, ?)", ["bad!", regex]).fetchone() == (False,)


@pytest.mark.parametrize(("pattern", "values"), [
    (r"\w+\W", ("a!", "a\u00e9", "a\u0662", "a_", "a\u0301", "a\u203f")),
    (r"[\W]+", ("!", "\u00e9", "\u2167", "_", "\u0301", "\u203f", "\u0378", "\u1c89", "\U0002ebf0")),
    (r"[\W_\]]+", ("_]", "\u203f", "\u00e9", "\u2167")),
    (r"[^\W]+", ("\u00e9\u0662_", "!", "\u0301", "\u203f")),
    (r"[^\Wa-z" "\u00e9]+", ("\u2167_", "\u00e9", "a", "!", "\u203f")),
    (r"[\w\W]", ("a", "!", "\u1c89", "\U0002ebf0")),
    (r"[^\w\W]", ("a", "!", "\u203f")),
    (r"(?i:[\Wa-z])[^\WA-Z]", ("Aa", "AA", "\u0345\u03b9", "\u03b9a")),
    (r"(?i)\W(?-i:[^\WA-Z])", ("!a", "!A", "\u0345\u03b9", "\u03b9a")),
    (r"\w+\\W", ("\u00e9\\W", "\u00e9W", "!\\W")),
])
def test_unicode_word_complement_agrees_with_the_publication_reader(pattern, values):
    schema = _word_schema(pattern)
    regex = _exported_pattern(schema)
    with duckdb.connect() as db:
        for value in values:
            try:
                table = arrow.to_arrow(schema, [{"$kind": "Tag", "$id": "a", "label": value}])["Tag"]
                assert table["label"].to_pylist() == [value]
                accepted = True
            except l0.L0Error as error:
                assert "pattern" in str(error)
                accepted = False
            assert db.execute("SELECT regexp_matches(?, ?)", [value, regex]).fetchone() == (accepted,), value
