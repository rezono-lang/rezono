"""Enum and member descriptions and exact mappings must lower to the public std-time schema's enum."""

from model_parity import lower_declarations, schema_file


MEMBERS = {
    "before": ("a ends before b starts", "time:intervalBefore"),
    "meets": ("a ends where b starts", "time:intervalMeets"),
    "overlaps": ("a starts first, b starts inside a, and a ends inside b", "time:intervalOverlaps"),
}


def test_lower_enum_metadata(tmp_path):
    oracle = schema_file("packs/std-time/schema/time.yaml")["enums"]["IntervalRelation"]
    declaration = {
        "enum": "IntervalRelation", "world": "closed", "values": list(MEMBERS),
        "description": oracle["description"],
        "memberMetadata": {name: {"description": text, "exactMappings": [iri]}
                           for name, (text, iri) in MEMBERS.items()},
    }
    actual = lower_declarations(tmp_path, "std-time", [declaration])["enums"]["IntervalRelation"]
    assert actual["description"] == oracle["description"]
    assert list(actual["permissible_values"]) == list(MEMBERS)
    for name in MEMBERS:
        member = actual["permissible_values"][name]
        expected = oracle["permissible_values"][name]
        assert (member.get("description"), member.get("exact_mappings")) == (
            expected["description"], expected["exact_mappings"]), name
