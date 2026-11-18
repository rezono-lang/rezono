"""Validate the recording before executing effects."""

import pytest

from wire_fixtures import entry, fixture


def test_recording_input(monkeypatch, tmp_path):
    load_recording = entry(monkeypatch, "recording_input", "load_recording")
    import json
    path = tmp_path / "case.json"
    original = fixture("recording")
    path.write_text(json.dumps(original), encoding="utf-8")
    assert load_recording(path) == original
    for change in ({"limit": 0}, {"limit": True}, {"sweeps": [[["r", "token"]]]}, {"unexpected": True}):
        path.write_text(json.dumps({**original, **change}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_recording(path)
