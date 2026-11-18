"""Load offline fixtures and production ports through their ordinary Python modules."""

import importlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / "tests" / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))


def entry(monkeypatch, module, function):
    monkeypatch.syspath_prepend(str(ROOT))
    return getattr(importlib.import_module(module), function)
