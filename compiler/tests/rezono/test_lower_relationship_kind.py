"""A relationship kind must lower to the public std-decision schema's `represents_relationship`."""

import pytest

from model_parity import kind, lower_declarations, schema_file, slot


def test_lower_relationship_kind(tmp_path):
    oracle = schema_file("packs/std-decision/schema/decision.yaml")["classes"]["Ground"]
    ground = kind("Ground", slot("decision", "Decision"), slot("rests_on", "Decision"), relationship=True)
    actual = lower_declarations(tmp_path, "std-decision", [ground], external=["Decision"])["classes"]["Ground"]
    assert actual.get("represents_relationship") is oracle["represents_relationship"] is True

    # Counter-case: the same two kind-valued slots without the marker are an ordinary kind.
    plain = kind("Ground", slot("decision", "Decision"), slot("rests_on", "Decision"))
    actual = lower_declarations(tmp_path, "std-decision", [plain], external=["Decision"])["classes"]["Ground"]
    assert not actual.get("represents_relationship")
