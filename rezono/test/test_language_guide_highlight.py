"""Syntax-highlighted light and dark SVG previews for the language guide excerpt
(decisions/language-guide-highlight.md)."""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
REZONO = ROOT / "rezono"
GUIDE = REZONO / "README.md"
GENERATOR = REZONO / "src" / "render-excerpt-svg.ts"
THEME = REZONO / "highlight-theme.json"
LIGHT_SVG = REZONO / "assets" / "excerpt-light.svg"
DARK_SVG = REZONO / "assets" / "excerpt-dark.svg"

TOKEN_KINDS = (
    "comment",
    "function",
    "identifier",
    "keyword",
    "number",
    "operator",
    "punctuation",
    "source",
    "state",
    "string",
    "type",
)
SURFACE_KEYS = ("background", "border", "foreground")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b")
FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.M | re.S)
PICTURE = re.compile(r"<picture>\s*(.*?)\s*</picture>", re.S)
SOURCE_TABLE_HEADER = "| File | What |"
SVG_NS = "{http://www.w3.org/2000/svg}"


class MissingLanguageGuideHighlight(AssertionError):
    """The language guide SVG syntax highlighter, theme data, generated SVGs, or README display is missing or invalid."""


def _normalise_lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _first_excerpt(guide_text: str) -> tuple[re.Match[str], str]:
    match = FENCE.search(guide_text)
    if match is None:
        raise MissingLanguageGuideHighlight("rezono/README.md has no fenced code block")
    return match, match.group(2).rstrip("\n")


def _svg_lines_and_fills(svg_bytes: bytes) -> tuple[list[str], set[str]]:
    try:
        root = ET.fromstring(svg_bytes)
    except ET.ParseError as error:
        raise MissingLanguageGuideHighlight(f"invalid SVG XML: {error}") from error
    lines: list[str] = []
    fills: set[str] = set()
    for elem in root.iter():
        tag = elem.tag.removeprefix(SVG_NS)
        if tag == "text":
            lines.append("".join(elem.itertext()))
            fill = elem.attrib.get("fill")
            if fill:
                fills.add(fill.lower())
        elif tag == "tspan":
            fill = elem.attrib.get("fill")
            if fill:
                fills.add(fill.lower())
    return lines, fills


def test_regenerating_excerpt_svgs_produces_identical_bytes(tmp_path):
    missing = [str(p.relative_to(ROOT)) for p in (GENERATOR, THEME, LIGHT_SVG, DARK_SVG) if not p.is_file()]
    if missing:
        raise MissingLanguageGuideHighlight(f"missing required highlight files: {missing}")

    run_a = tmp_path / "run-a"
    run_b = tmp_path / "run-b"
    run_a.mkdir()
    run_b.mkdir()
    for target in (run_a, run_b):
        result = subprocess.run(
            ["node", str(GENERATOR), "--out-dir", str(target)],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            raise MissingLanguageGuideHighlight(
                f"render-excerpt-svg.ts failed ({result.returncode}): {result.stderr or result.stdout}"
            )

    problems: list[str] = []
    for name, committed in (("excerpt-light.svg", LIGHT_SVG), ("excerpt-dark.svg", DARK_SVG)):
        first = (run_a / name).read_bytes() if (run_a / name).is_file() else None
        second = (run_b / name).read_bytes() if (run_b / name).is_file() else None
        if first is None or second is None:
            problems.append(f"generator did not write {name}")
            continue
        if first != second:
            problems.append(f"regenerating {name} is not deterministic across two runs")
        if first != committed.read_bytes():
            problems.append(f"committed {committed.relative_to(ROOT)} differs from regenerated {name}")

    if problems:
        raise MissingLanguageGuideHighlight("\n".join(problems))


def test_excerpt_svg_text_matches_the_excerpt():
    guide = _normalise_lf(GUIDE.read_text(encoding="utf-8"))
    _, excerpt = _first_excerpt(guide)
    expected_lines = excerpt.split("\n")

    problems: list[str] = []
    for svg_path in (LIGHT_SVG, DARK_SVG):
        if not svg_path.is_file():
            problems.append(f"missing {svg_path.relative_to(ROOT)}")
            continue
        lines, fills = _svg_lines_and_fills(svg_path.read_bytes())
        if lines != expected_lines:
            problems.append(
                f"{svg_path.relative_to(ROOT)} text lines do not match the opening excerpt of rezono/README.md"
            )
        if len(fills) < 2:
            problems.append(
                f"{svg_path.relative_to(ROOT)} uses fewer than 2 fill colors ({sorted(fills)}); excerpt is not highlighted"
            )

    if problems:
        raise MissingLanguageGuideHighlight("\n".join(problems))


def test_highlight_theme_covers_every_token_kind_in_light_and_dark():
    if not THEME.is_file():
        raise MissingLanguageGuideHighlight("missing rezono/highlight-theme.json")

    try:
        data = json.loads(THEME.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MissingLanguageGuideHighlight(f"invalid JSON in rezono/highlight-theme.json: {error}") from error

    problems: list[str] = []
    themes = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(themes, dict):
        raise MissingLanguageGuideHighlight("rezono/highlight-theme.json must define a `themes` object")

    for mode in ("light", "dark"):
        palette = themes.get(mode)
        if not isinstance(palette, dict):
            problems.append(f"missing {mode!r} theme in rezono/highlight-theme.json")
            continue
        for key in SURFACE_KEYS:
            value = palette.get(key)
            if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
                problems.append(f"themes.{mode}.{key} must be a #RRGGBB hex color, got {value!r}")
        tokens = palette.get("tokens")
        if not isinstance(tokens, dict):
            problems.append(f"missing themes.{mode}.tokens in rezono/highlight-theme.json")
            continue
        missing_kinds = sorted(set(TOKEN_KINDS) - set(tokens))
        extra_kinds = sorted(set(tokens) - set(TOKEN_KINDS))
        if missing_kinds:
            problems.append(f"themes.{mode}.tokens missing token kinds: {missing_kinds}")
        if extra_kinds:
            problems.append(f"themes.{mode}.tokens has undeclared token kinds: {extra_kinds}")
        for kind in TOKEN_KINDS:
            color = tokens.get(kind)
            if isinstance(tokens, dict) and kind in tokens:
                if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
                    problems.append(f"themes.{mode}.tokens.{kind} must be a #RRGGBB hex color, got {color!r}")

    if (
        isinstance(themes.get("light"), dict)
        and isinstance(themes.get("dark"), dict)
        and themes["light"].get("background") == themes["dark"].get("background")
    ):
        problems.append("light and dark themes must have distinct background colors")

    if not GENERATOR.is_file():
        problems.append("missing rezono/src/render-excerpt-svg.ts")
    else:
        code = GENERATOR.read_text(encoding="utf-8")
        hardcoded = HEX_LITERAL.findall(code)
        if hardcoded:
            problems.append(f"rezono/src/render-excerpt-svg.ts must not hardcode hex colors: {hardcoded}")

    if problems:
        raise MissingLanguageGuideHighlight("\n".join(problems))


def test_language_guide_displays_highlighted_picture_and_color_legend():
    guide = _normalise_lf(GUIDE.read_text(encoding="utf-8"))
    first_block, _ = _first_excerpt(guide)
    table_pos = guide.find(SOURCE_TABLE_HEADER)
    if table_pos < 0:
        raise MissingLanguageGuideHighlight("rezono/README.md is missing its source-file table")

    between = guide[first_block.end():table_pos]
    picture_match = PICTURE.search(between)
    if picture_match is None:
        raise MissingLanguageGuideHighlight(
            "rezono/README.md must place a <picture> block underneath the opening code block and before the source table"
        )

    problems: list[str] = []
    inner = picture_match.group(1)

    dark_source = re.search(
        r"<source\b(?=[^>]*\bmedia=[\"']\(prefers-color-scheme:\s*dark\)[\"'])"
        r"(?=[^>]*\bsrcset=[\"']assets/excerpt-dark\.svg[\"'])[^>]*/?>",
        inner,
    )
    if dark_source is None:
        problems.append("<picture> must include <source media=\"(prefers-color-scheme: dark)\" srcset=\"assets/excerpt-dark.svg\">")

    img_match = re.search(r"<img\b[^>]*>", inner)
    if img_match is None:
        problems.append("<picture> must include an <img> element for the light SVG")
    else:
        img_tag = img_match.group(0)
        src_match = re.search(r"\bsrc=[\"']([^\"']+)[\"']", img_tag)
        alt_match = re.search(r"\balt=[\"']([^\"']+)[\"']", img_tag)
        if not src_match or src_match.group(1) != "assets/excerpt-light.svg":
            problems.append("<img> inside <picture> must set src=\"assets/excerpt-light.svg\"")
        if not alt_match or len(alt_match.group(1).split()) < 4:
            problems.append("<img> inside <picture> must carry a descriptive alt text (at least 4 words)")

    for svg_path in (LIGHT_SVG, DARK_SVG):
        if not svg_path.is_file():
            problems.append(f"referenced image does not exist: {svg_path.relative_to(ROOT)}")

    after_picture = between[picture_match.end():].splitlines()
    legend_line = next((line.strip() for line in after_picture if line.strip()), "")
    if not legend_line:
        problems.append("missing one-line color legend directly underneath </picture>")
    else:
        if legend_line.startswith(("#", "|", "```")):
            problems.append(f"color legend must be a plain single line, not {legend_line!r}")
        lower = legend_line.lower()
        for kind in ("keyword", "type", "number", "comment"):
            if kind not in lower:
                problems.append(f"one-line color legend must name the color for {kind!r}: {legend_line!r}")

    if problems:
        raise MissingLanguageGuideHighlight("\n".join(problems))
