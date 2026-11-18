"""Exercise the public request preview on actual files, including private copies edited by CI."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def preview(teams, catalog, *command):
    entry = ROOT / "request_preview.py"
    assert entry.is_file(), "Missing public platform request preview"
    args = [sys.executable, str(entry), "--pack", str(ROOT), "--teams", str(teams),
            "--catalog", str(catalog), *command]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def copy_requests(tmp_path):
    teams = tmp_path / "teams"
    shutil.copytree(ROOT / "teams", teams)
    catalog = tmp_path / "catalog.json"
    shutil.copyfile(ROOT / "tenant-catalog.json", catalog)
    return teams, catalog
