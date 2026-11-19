"""The round claim references on the complete manifest, from decisions/admission-transport.md section 2.

Beside `completeness_receipts`, the complete manifest carries an optional `rounds` list of archived-file
references to the submitted round claims. Each reference is pinned like any other archived file.
"""

from pathlib import Path

import pytest
import yaml

from contracts.validate import validator

ROOT = Path(__file__).resolve().parents[3]
EPOCH = ROOT / "contracts/fixtures/manifest/Manifest/valid/epoch.yaml"
CLAIM = {"file": "observations/submitted/claim.json", "uri": "archive/claim.json", "sha256": "0123456789abcdef" * 4}


def errors(document):
    return [result.message for result in validator("manifest.yaml").validate(document, "Manifest").results]


def test_manifest_lists_round_claims():
    manifest = yaml.safe_load(EPOCH.read_text(encoding="utf-8"))
    assert errors(manifest) == []  # control: the fixture is valid as it is
    assert errors(manifest | {"rounds": [CLAIM]}) == []
    assert errors(manifest | {"rounds": [{k: v for k, v in CLAIM.items() if k != "sha256"}]})
    assert errors(manifest | {"rounds": [CLAIM | {"verdict": "proved"}]})
