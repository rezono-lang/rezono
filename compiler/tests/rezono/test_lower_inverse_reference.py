"""An inverse slot must lower as the same slot without `inverse`, plus the LinkML slot property `inverse`."""

import pytest

from model_parity import kind, lower_declarations, slot


PARTY = kind("Party", slot("holder", "Holder"))


def holder(**inverse):
    return kind("Holder", slot("parties", "Party", card="+", **inverse))


def test_lower_inverse_reference(tmp_path):
    # LinkML's metamodel names the forward slot of an inverse with the slot property `inverse`.
    plain = lower_declarations(tmp_path, "sample", [PARTY, holder()])["classes"]["Holder"]["attributes"]["parties"]
    actual = lower_declarations(tmp_path, "sample", [PARTY, holder(inverse="holder")])
    assert actual["classes"]["Holder"]["attributes"]["parties"] == plain | {"inverse": "holder"}
    assert "inverse" not in actual["classes"]["Party"]["attributes"]["holder"]

    # Counter-cases: the forward slot must exist on the target kind, and it must point at the declaring kind.
    with pytest.raises(AssertionError):
        lower_declarations(tmp_path, "sample", [PARTY, holder(inverse="owner")])
    other = kind("Other", slot("parties", "Party", card="+", inverse="holder"))
    with pytest.raises(AssertionError):
        lower_declarations(tmp_path, "sample", [PARTY, holder(), other])
