"""A valid ODCS document can still describe an epoch different from this role's index."""

import pytest
import yaml

import accept
from acceptance_sample import AT, objects


def test_odcs_version_must_identify_the_same_epoch_as_its_index():
    sample = objects()
    contract = yaml.safe_load(sample["contract.odcs.yaml"])
    schema, manifest, dataset = contract["version"].split("@")
    assert manifest == "m-7"
    other_versions = [(schema, "m-8", dataset), (schema, manifest, "d-" + "b" * 64),
                      ("s-" + "b" * 64, manifest, dataset)]
    for parts in other_versions:
        contract["version"] = "@".join(parts)
        sample["contract.odcs.yaml"] = yaml.safe_dump(contract).encode()
        assert accept.published(sample, AT)["contract.odcs.yaml"]["state"] == "failed", parts
