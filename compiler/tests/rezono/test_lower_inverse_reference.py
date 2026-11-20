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


def test_inverse_refuses_mutual_inverse(tmp_path):
    # Two slots declaring each other as inverse leave no forward slot to read from.
    mutual_party = kind("Party", slot("holder", "Holder", inverse="parties"))
    with pytest.raises(AssertionError, match="is itself an inverse, not a forward slot"):
        lower_declarations(tmp_path, "sample", [mutual_party, holder(inverse="holder")])

    mutual_same_kind = kind(
        "Node",
        slot("left", "Node", card="*", inverse="right"),
        slot("right", "Node", card="*", inverse="left"),
    )
    with pytest.raises(AssertionError, match="is itself an inverse, not a forward slot"):
        lower_declarations(tmp_path, "sample", [mutual_same_kind])

    chained = [
        kind("Party", slot("holder", "Holder"), slot("mirror", "Holder", inverse="parties")),
        holder(inverse="holder"),
    ]
    with pytest.raises(AssertionError, match="is itself an inverse, not a forward slot"):
        lower_declarations(tmp_path, "sample", chained)


def test_inverse_refuses_self_inverse(tmp_path):
    # A slot cannot declare itself as its own forward slot.
    self_inverse = kind("Node", slot("peer", "Node", card="*", inverse="peer"))
    with pytest.raises(AssertionError, match="cannot be the slot itself"):
        lower_declarations(tmp_path, "sample", [self_inverse])

    # A same-kind inverse that points at a distinct forward slot still lowers.
    tree = kind(
        "Node",
        slot("parent", "Node", card="?"),
        slot("children", "Node", card="*", inverse="parent"),
    )
    lowered = lower_declarations(tmp_path, "sample", [tree])
    assert lowered["classes"]["Node"]["attributes"]["children"]["inverse"] == "parent"
    assert "inverse" not in lowered["classes"]["Node"]["attributes"]["parent"]
