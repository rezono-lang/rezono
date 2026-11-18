"""Invoke the example's public command. Fixtures contain only synthetic proposal files."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def proposal(tmp_path):
    assert (ROOT / "request_preview.py").is_file(), "Public platform request preview is missing"
    from request_preview_case import copy_requests
    return copy_requests(tmp_path)


def query(teams, catalog, *command):
    from request_preview_case import preview
    return preview(teams, catalog, *command)


def quota(owner, amount):
    return {"id": owner + "-cpu", "owner": owner, "dimension": "cores", "amount": amount}
