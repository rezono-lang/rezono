"""Expose the canonical printer (`rezono/src/print.ts`) as the single formatter (`rezono fmt`)
(decisions/language-rezono-1.md, sections 1 and 8)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
FMT = ROOT / "rezono" / "src" / "fmt.ts"
PACKAGE_JSON = ROOT / "rezono" / "package.json"

MESSY = """\
rezono   0
pack   sample

-- formatting comment removed in canonical output
kind Item   world closed
    name:   Text
    count:   Int
"""

CANONICAL = """\
rezono 0
pack sample
kind Item world closed
  name: Text
  count: Int
"""

INVALID = "rezono 0\npack sample\nkind\n"


class MissingRezonoFmt(AssertionError):
    """rezono/src/fmt.ts (and package.json `fmt` script) did not format canonically, check, or refuse invalid input."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRezonoFmt,
    reason="M3: decisions/language-rezono-1.md: Add rezono/src/fmt.ts (wired as `fmt` in rezono/package.json) "
           "exposing rezono/src/print.ts (`printModule`) as the canonical formatter: in-place idempotent formatting, "
           "`--check` exiting 0 when canonical and 1 without modifying when unformatted, and non-zero exit with "
           "diagnostics on stderr without modifying invalid files. Read sections 1 and 8.",
)
def test_rezono_fmt_formats_canonically(tmp_path):
    if not FMT.is_file():
        raise MissingRezonoFmt("missing rezono/src/fmt.ts")

    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    problems = []
    if "fmt" not in (pkg.get("scripts") or {}):
        problems.append("rezono/package.json scripts missing 'fmt'")

    messy_file = tmp_path / "sample.rezono"
    messy_file.write_text(MESSY, encoding="utf-8")

    # --check on unformatted input: exit 1, file untouched.
    check_dirty = subprocess.run(
        ["node", str(FMT), "--check", str(messy_file)],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    if check_dirty.returncode != 1 or messy_file.read_text(encoding="utf-8") != MESSY:
        problems.append({"check_dirty": check_dirty.returncode, "text": messy_file.read_text(encoding="utf-8")})

    # In-place format produces exact canonical text, idempotent on second run.
    fmt_once = subprocess.run(["node", str(FMT), str(messy_file)], cwd=ROOT, capture_output=True, encoding="utf-8")
    if fmt_once.returncode != 0 or messy_file.read_text(encoding="utf-8") != CANONICAL:
        problems.append({"fmt_once": fmt_once.returncode, "stderr": fmt_once.stderr, "text": messy_file.read_text(encoding="utf-8")})

    fmt_twice = subprocess.run(["node", str(FMT), str(messy_file)], cwd=ROOT, capture_output=True, encoding="utf-8")
    if fmt_twice.returncode != 0 or messy_file.read_text(encoding="utf-8") != CANONICAL:
        problems.append({"fmt_twice": fmt_twice.returncode})

    # --check on already canonical input: exit 0.
    check_clean = subprocess.run(
        ["node", str(FMT), "--check", str(messy_file)],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    if check_clean.returncode != 0:
        problems.append({"check_clean": check_clean.returncode, "stderr": check_clean.stderr})

    # Invalid file: non-zero exit, stderr diagnostic, original bytes preserved.
    bad_file = tmp_path / "broken.rezono"
    bad_file.write_text(INVALID, encoding="utf-8")
    fmt_bad = subprocess.run(["node", str(FMT), str(bad_file)], cwd=ROOT, capture_output=True, encoding="utf-8")
    if fmt_bad.returncode == 0 or not fmt_bad.stderr.strip() or bad_file.read_text(encoding="utf-8") != INVALID:
        problems.append({"fmt_bad": fmt_bad.returncode, "stderr": fmt_bad.stderr})

    if problems:
        raise MissingRezonoFmt(json.dumps(problems, indent=2))
