"""The module form only accepts typed slot constraints in version two."""

from pathlib import Path

import pytest
from linkml.validator import validate


SCHEMA = str(Path(__file__).resolve().parents[2] / "rezono-module.yaml")
SLOT = {"slot": "value", "type": "Int", "card": "?"}


def findings(version: int, *slots: dict[str, object]):
    declaration = {"kind": "Item", "slots": list(slots), "derived": []}
    form = {
        "format": f"rezono.module/{version}",
        "module": {"rezono": "0", "pack": "sample", "use": [], "decls": [declaration]},
        "spans": [],
    }
    return validate(form, SCHEMA, "ModuleForm").results


@pytest.mark.parametrize(
    "slot",
    [
        {**SLOT, "type": "Text", "card": "*", "constraints": [{"cardinality": ["1", "3"]}]},
        {**SLOT, "constraints": [{"minimum": "-1.5"}, {"maximum": "200"}]},
        {**SLOT, "type": "Text", "constraints": [{"pattern": "^[0-9]+$"}]},
    ],
)
def test_constraints_require_version_two_even_with_an_unconstrained_slot(slot):
    label = {"slot": "label", "type": "Text"}
    assert findings(2, label, slot) == []
    assert findings(1, label, slot)


def test_version_one_still_accepts_an_unconstrained_slot():
    assert findings(1, SLOT) == []


@pytest.mark.parametrize(
    "constraints",
    [
        None,
        [],
        {"minimum": "1"},
        [{}],
        [{"unknown": "1"}],
        [{"minimum": "1", "maximum": "2"}],
        [{"minimum": 1}],
        [{"maximum": "1/2"}],
        [{"cardinality": ["1"]}],
        [{"cardinality": ["1", "3", "4"]}],
        [{"cardinality": ["1", "-3"]}],
        [{"pattern": ["^foo$"]}],
    ],
)
def test_version_two_refuses_malformed_slot_constraints(constraints):
    assert findings(2, {**SLOT, "constraints": constraints})
