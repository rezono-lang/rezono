"""The public example generator and compiler agree on the recorded ledger close."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
GENERATED = ("facts/population.yaml", "facts/ledger.yaml", "scenarios/2-close-october.yaml")


def test_the_generator_writes_the_same_bytes_again(tmp_path):
    subprocess.run([sys.executable, str(HERE / "generate.py"), str(tmp_path)], check=True)
    for path in GENERATED:
        assert (tmp_path / path).read_bytes() == (HERE / path).read_bytes(), path


def test_the_close_is_what_the_compiler_writes():
    """generate.py writes the close of October with the reference's own row hash; the compiler's close
    command gives the same close, so two implementations agree on what a closed row is."""
    out = subprocess.run([sys.executable, "-m", "rezono_compiler", "close", str(HERE), "--close", "october-2026",
                          "--until", "2026-11-01", "--file", "facts/ledger.yaml"], check=True, capture_output=True, text=True)
    change, = json.loads(out.stdout)["changes"]
    mine, = yaml.safe_load((HERE / "scenarios" / "2-close-october.yaml").read_text("utf-8"))["period_close"]
    assert {"id": change["key"], **change["values"]} == mine
