"""The public ODCS loss list must account for admission semantics the contract drops."""

import json
from pathlib import Path

import pytest
import yaml

import odcs
from rezono_publication import l0


@pytest.mark.xfail(strict=True, reason="Declare the dropped control-owner and reviewed-change requirement in edge/plugins/connectors/odcs.losses.yaml. Read decisions/odcs-quality-coverage.md.")
def test_loss_list_names_the_omitted_control_owner_and_review():
    schema = {"rezono": "1.0", "base": "https://example.org/limits/", "pack": "limits",
              "kinds": {"Limit": {"id": {"type": "Text"}, "world": "closed",
                                  "plane": "control", "owner": "sample_council", "slots": {
                                      "decision": {"card": "1", "type": "Text", "states": ["known"]}}}}}
    assert l0.schema_id(schema)
    doc = odcs.contract(schema)
    assert "sample_council" not in json.dumps(doc)
    losses = yaml.safe_load(Path(__file__).with_name("odcs.losses.yaml").read_text("utf-8"))
    assert any(loss["subject"] == "check" and loss["fate"] == "dropped"
               and all(word in loss["what"].lower() for word in ("control", "owner", "review"))
               for loss in losses["losses"])
