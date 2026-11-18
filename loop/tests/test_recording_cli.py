"""Replay the checked-in trace through the ordinary command."""

import pytest

from wire_fixtures import entry


def test_recording_cli(monkeypatch, capsys):
    main = entry(monkeypatch, "recording_cli", "main")
    import json
    from wire_fixtures import ROOT
    assert main([str(ROOT / "tests" / "fixtures" / "recording.json")]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "plans": [["seed"], ["prepare"], ["publish"]], "outcome": "success", "rounds": 3}
