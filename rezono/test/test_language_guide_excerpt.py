"""The language guide opens with a verbatim Rezono excerpt from examples/subsidy-scheme/rezono/award.rezono
and links to where the syntax is described, before its table of source files
(decisions/language-guide-highlight.md)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "rezono" / "README.md"
AWARD_SOURCE = ROOT / "examples" / "subsidy-scheme" / "rezono" / "award.rezono"
FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.M | re.S)
SOURCE_TABLE_HEADER = "| File | What |"
AGREED_FENCE_LABEL = "haskell"


class MissingLanguageGuideExcerpt(AssertionError):
    """rezono/README.md does not yet open with the agreed fenced excerpt from examples/subsidy-scheme/rezono/award.rezono."""


def _normalise_lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _is_line_bounded_slice(excerpt: str, source: str) -> bool:
    """True when `excerpt` matches a contiguous sequence of complete lines in `source` byte-for-byte."""
    excerpt_lines = excerpt.rstrip("\n").split("\n")
    source_lines = source.rstrip("\n").split("\n")
    width = len(excerpt_lines)
    if width == 0 or width > len(source_lines):
        return False
    return any(source_lines[i:i + width] == excerpt_lines for i in range(len(source_lines) - width + 1))


@pytest.mark.xfail(
    strict=True,
    raises=MissingLanguageGuideExcerpt,
    reason=(
        "M3: decisions/language-guide-highlight.md: Waits for "
        "examples/subsidy/test_subsidy_scheme_award.py--test_subsidy_scheme_award_in_rezono. "
        "Start rezono/README.md before its source-file table with a `haskell`-fenced excerpt copied "
        "byte-for-byte from examples/subsidy-scheme/rezono/award.rezono and links to where the syntax "
        "is described."
    ),
)
def test_language_guide_starts_with_subsidy_award_excerpt():
    problems: list[str] = []

    if not AWARD_SOURCE.is_file():
        raise MissingLanguageGuideExcerpt("missing examples/subsidy-scheme/rezono/award.rezono")

    guide = _normalise_lf(GUIDE.read_text(encoding="utf-8"))
    source = _normalise_lf(AWARD_SOURCE.read_text(encoding="utf-8"))

    table_pos = guide.find(SOURCE_TABLE_HEADER)
    if table_pos < 0:
        raise MissingLanguageGuideExcerpt("rezono/README.md is missing its source-file table")

    first_block = FENCE.search(guide)
    if first_block is None:
        raise MissingLanguageGuideExcerpt("rezono/README.md contains no fenced code block")

    if first_block.start() > table_pos:
        problems.append("the first fenced code block of rezono/README.md must appear before the source-file table")

    label, body = first_block.group(1), first_block.group(2)
    if label != AGREED_FENCE_LABEL:
        problems.append(f"first fenced code block uses label {label!r}, expected {AGREED_FENCE_LABEL!r}")

    lines = body.rstrip("\n").split("\n") if body.strip() else []
    non_empty = [line for line in lines if line.strip()]
    if len(non_empty) < 3:
        problems.append("first fenced code block must show a substantive Rezono excerpt (at least 3 non-empty lines)")
    if len(lines) > 20:
        problems.append(f"first fenced code block has {len(lines)} lines, expected at most 20")
    if not any(line.lstrip().startswith("derived ") for line in lines):
        problems.append("first fenced code block must include at least one `derived` calculation rule")
    if not _is_line_bounded_slice(body, source):
        problems.append(
            "first fenced code block must match a contiguous slice of "
            "examples/subsidy-scheme/rezono/award.rezono byte-for-byte"
        )

    opening = guide[:table_pos]
    for link in ("](../docs/rezono/v0.md", "](../docs/rezono/expressions.md"):
        if link not in opening:
            problems.append(f"rezono/README.md must link to {link} before the source-file table")

    if problems:
        raise MissingLanguageGuideExcerpt("\n".join(problems))
