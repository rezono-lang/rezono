"""Replay the checked-in trace through the ordinary command."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-fixture-evidence.md. Implement loop/recording_cli.py. Waits for test_recording_input and test_replay. Replay the checked-in trace through the ordinary command.")
def test_recording_cli(monkeypatch, capsys):
    main = entry(monkeypatch, "recording_cli", "main")
    import json
    from wire_fixtures import ROOT
    assert main([str(ROOT / "tests" / "fixtures" / "recording.json")]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "plans": [["seed"], ["prepare"], ["publish"]], "outcome": "success", "rounds": 3}
