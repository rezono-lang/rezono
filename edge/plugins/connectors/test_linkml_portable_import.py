"""LinkML import references use path separators from the exchange format on every host."""

import ntpath
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import linkml_schema


def test_linkml_import_reference_uses_exchange_separators_on_windows(monkeypatch):
    # Exercise the actual Windows standard-library path behavior on Linux CI as well.
    monkeypatch.setattr(linkml_schema, "os", SimpleNamespace(path=ntpath))
    files = linkml_schema.export(Path(__file__).parent / "fixtures/linkml")
    module = yaml.safe_load(files["linkml-fixture/parts/whole.yaml"])
    assert module["imports"] == ["linkml:types", "../base"]
