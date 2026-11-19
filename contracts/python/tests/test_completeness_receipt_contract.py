"""The contract of a completeness receipt and of its candidate references in a manifest.

The expected shape is the one fixed in decisions/scoped-completeness.md, section 1 and
"Admission and replay transport": `CompletenessReceipt` alongside `Observation` with exactly
`id`, `source`, `issuer`, `scope`, `cut`, `inventory` and `content`, and an optional
`completeness_receipts` list of archived-file references on the complete manifest.
"""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from contracts.validate import validator

ROOT = Path(__file__).resolve().parents[3]
EPOCH = ROOT / "contracts/fixtures/manifest/Manifest/valid/epoch.yaml"
DIGEST = "0123456789abcdef" * 4


def archived(name):
    return {"file": name, "uri": f"archive/{name}", "sha256": DIGEST}


RECEIPT = {
    "id": "fedcba9876543210" * 4,
    "source": {"kind": "query", "name": "example-register", "revision": "snapshot-17", "position": "/enumeration"},
    "issuer": {"id": "reader", "authorization": archived("authorized-issuer.json")},
    "scope": {"definition": archived("scope-definition.json"), "query": "partitions",
              "bindings": [{"name": "register", "type": "Text", "value": "example-register"}]},
    "cut": {"frontier": {"source_id": "example-register", "position": "snapshot-17"}},
    "inventory": archived("expected-members.json"),
    "content": archived("captured-content.json"),
}


def errors(document, schema, target):
    return [result.message for result in validator(schema).validate(document, target).results]


def without(document, key):
    return {k: v for k, v in document.items() if k != key}


def test_completeness_receipt_contract():
    manifest = yaml.safe_load(EPOCH.read_text(encoding="utf-8"))
    assert errors(manifest, "manifest.yaml", "Manifest") == []  # control: the fixture is valid as it is

    with_receipts = manifest | {"completeness_receipts": [archived("receipt.json")]}
    assert errors(with_receipts, "manifest.yaml", "Manifest") == []
    unpinned = manifest | {"completeness_receipts": [without(archived("receipt.json"), "sha256")]}
    assert errors(unpinned, "manifest.yaml", "Manifest")

    assert errors(RECEIPT, "observation.yaml", "CompletenessReceipt") == []
    # Every field of the receipt is required, and nothing else is allowed.
    for field in RECEIPT:
        assert errors(without(RECEIPT, field), "observation.yaml", "CompletenessReceipt"), field
    assert errors(RECEIPT | {"complete": True}, "observation.yaml", "CompletenessReceipt")
    # Digests are lowercase hexadecimal SHA-256, references are pinned, and the cut has a frontier.
    assert errors(RECEIPT | {"id": DIGEST.upper()}, "observation.yaml", "CompletenessReceipt")
    assert errors(RECEIPT | {"inventory": without(archived("x.json"), "sha256")},
                  "observation.yaml", "CompletenessReceipt")
    assert errors(RECEIPT | {"cut": {}}, "observation.yaml", "CompletenessReceipt")
    unbound = deepcopy(RECEIPT)
    del unbound["scope"]["bindings"][0]["type"]
    assert errors(unbound, "observation.yaml", "CompletenessReceipt")
    unissued = deepcopy(RECEIPT)
    del unissued["issuer"]["authorization"]
    assert errors(unissued, "observation.yaml", "CompletenessReceipt")
