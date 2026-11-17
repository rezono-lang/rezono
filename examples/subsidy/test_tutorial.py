"""docs/tutorial.md runs as written (RV-D05): its commands, on a copy of the pack, give what the page says.

The test reads the page itself. Every `python` command in a bash block runs in order; the scenario the
reader is asked to write is taken from the page and saved where the page says; and every line the page
quotes from the pack is still in the pack, so the tutorial cannot drift from what it describes.
Needs the compiler with DuckDB.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("rede_compiler")

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
SCHEME = HERE.parent / "subsidy-scheme"  # the definition the pack imports (RV-X35)
PAGE = (ROOT / "docs" / "tutorial.md").read_text(encoding="utf-8")
SCENARIO = "examples/subsidy/scenarios/5-higher-allowance.yaml"
COMMANDS = ["python -m rede_compiler check examples/subsidy",
            "python -m rede_compiler compile examples/subsidy generated/subsidy",
            "python -m rede_compiler explain examples/subsidy generated/subsidy-explained",
            "python examples/subsidy/reference.py --summary",
            "python examples/subsidy/reference.py --summary"]


def blocks(language: str) -> list[str]:
    """The fenced blocks of the page in that language ("" for a fence without one), in page order."""
    out, inside, lang, lines = [], False, "", []
    for line in PAGE.splitlines():
        if line.startswith("```"):
            if inside and lang == language:
                out.append("\n".join(lines) + "\n")
            inside, lang, lines = not inside, line[3:].strip(), []
        elif inside:
            lines.append(line)
    return out


def test_every_quoted_line_is_in_the_pack():
    """A yaml or rule block quotes the pack or the scheme it imports, except the scenario the reader writes."""
    pack = "\n".join(p.read_text(encoding="utf-8") for at in (HERE, SCHEME)
                     for d in ("schema", "facts", "rules", "calc", "messages") for p in sorted((at / d).glob("*")))
    lines = {line.strip() for line in pack.splitlines()}
    quoted = [b for b in blocks("yaml") + blocks("") if '"par-07"' not in b]
    assert len(quoted) >= 8
    missing = [line for b in quoted for line in b.splitlines() if line.strip() and line.strip() not in lines]
    assert missing == []


def test_the_commands_give_what_the_page_says(tmp_path):
    commands = [line.split("#")[0].strip() for b in blocks("bash") for line in b.splitlines() if line.startswith("python ")]
    assert commands == COMMANDS
    assert SCENARIO in PAGE and not (ROOT / SCENARIO).exists()
    scenario, = [b for b in blocks("yaml") if '"par-07"' in b]

    # A copy of the pack at the same depth, next to packs/, so the commands run from a root as on the page.
    shutil.copytree(HERE, tmp_path / "examples" / "subsidy", ignore=shutil.ignore_patterns("expected", "__pycache__"))
    shutil.copytree(SCHEME, tmp_path / "examples" / "subsidy-scheme")
    shutil.copytree(ROOT / "packs", tmp_path / "packs")

    def run(command: str) -> str:
        return subprocess.run([sys.executable, *command.split()[1:]], cwd=tmp_path, check=True, capture_output=True, text=True).stdout

    assert "ok examples/subsidy" in run(commands[0])
    run(commands[1])
    assert (tmp_path / "generated" / "subsidy" / "bundle" / "schema-bundle.json").exists()

    # The proof the page shows is the proof the command writes, field for field.
    run(commands[2])
    shown = json.loads(blocks("json")[0])
    proofs = json.loads((tmp_path / "generated" / "subsidy-explained" / "0-applications" / "proofs.json").read_text(encoding="utf-8"))
    proof = next(p for p in proofs if p["root"] == shown["root"])
    witness, = [w for w in proof["witnesses"] if w["conclusion"] == shown["root"]]
    told = shown["witnesses"][0]
    assert (witness["rule_id"], witness["bindings"]) == (told["rule_id"], told["bindings"])
    assert [(p["row"], p["polarity"]) for p in witness["premises"]] == [(p["row"], p["polarity"]) for p in told["premises"]]

    first = run(commands[3]).splitlines()
    assert first[0].startswith("0-applications ")
    for part in ("'applications': 240", "'unknown': 17", "'undecided': 0", "'awarded': 205", "'total_cents': 49800714"):
        assert part in first[0], part
    assert "'total_cents': 50898411" in first[-1]

    (tmp_path / SCENARIO).write_text(scenario, encoding="utf-8")
    after = run(commands[4]).splitlines()
    assert after[:-1] == first
    assert after[-1].startswith("5-higher-allowance ") and "'total_cents': 51558411" in after[-1]
    assert "'undecided': 3" in after[-1]
