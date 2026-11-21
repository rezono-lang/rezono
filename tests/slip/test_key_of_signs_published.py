"""A publication carries the key of signs (docs/vision.md, Reading; decisions/release-1-scope.md, "The key of signs").

The schema bundle a publication archives, the manifest's `compiled` entry for bundle/schema-bundle.json, holds the
statuses, tones, signs and differences of packs/std-view/key.yaml, entry for entry and in their order there, and in
its messages the label each of them names, in every language of std-view, with the text of packs/std-view/messages.
Both are read here as the oracle. tests/fixtures/slip does not import std-view: every publication carries the key.
"""

import hashlib
import json
import re

import pytest
import yaml
from slip_support import ROOT, publish_main

STD_VIEW = ROOT / "packs" / "std-view"
PARTS = ("statuses", "tones", "signs", "differences")


class MissingKeyOfSigns(AssertionError):
    """The schema bundle of the publication has no key of signs."""


def texts(resource: str) -> dict[str, str]:
    """The text of every one-line message of a MessageFormat 2 resource, by id."""
    body = resource.split("\n---\n", 1)[1] if "\n---\n" in resource else resource
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^([A-Za-z0-9_.-]+)\s*=\s*(.*)$", body, re.MULTILINE)}


def test_key_of_signs_published(tmp_path):
    store, manifest = publish_main(tmp_path)
    [compiled] = [item for item in manifest["compiled"] if item["file"] == "bundle/schema-bundle.json"]
    data = (store / compiled["uri"].split("/", 3)[3]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == compiled["sha256"]
    bundle = json.loads(data)
    if "key" not in bundle:
        raise MissingKeyOfSigns(f"the schema bundle has no key: {sorted(bundle)}")

    key = yaml.safe_load((STD_VIEW / "key.yaml").read_text(encoding="utf-8"))
    assert {part: bundle["key"].get(part) for part in PARTS} == {part: key[part] for part in PARTS}

    labels = sorted({item["label_message"] for part in PARTS for item in key[part]})
    languages = sorted(path.stem for path in (STD_VIEW / "messages").glob("*.mf2"))
    assert languages
    for lang in languages:
        want = texts((STD_VIEW / "messages" / f"{lang}.mf2").read_text(encoding="utf-8"))
        got: dict[str, str] = {}
        for resource in bundle["messages"]:
            if resource["lang"] == lang:
                got |= texts(resource["resource"])
        assert {label: got.get(label) for label in labels} == {label: want[label] for label in labels}, lang
