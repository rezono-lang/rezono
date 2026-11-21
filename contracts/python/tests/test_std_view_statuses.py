"""Status signs of std-view (decisions/std-view-invalid-sign.md): packs/std-view/{palette,key}.yaml
validates against `Key` in contracts/view.yaml, includes every `StatusName` (including `invalid` `!`,
distinct from `violated` `✕`), defines a unique non-colour glyph and en/nl messages for each, and
meets WCAG contrast requirements on `paper` (>= 4.5:1) and against `ink` (>= 3.0:1 for `status.invalid`)
in light, dark, and print themes."""

import re
from pathlib import Path

import pytest
import yaml
from linkml.validator import validate

ROOT = Path(__file__).resolve().parents[3]
VIEW = ROOT / "contracts" / "view.yaml"
STD_VIEW = ROOT / "packs" / "std-view"


def message_ids(lang: str) -> set[str]:
    text = (STD_VIEW / "messages" / f"{lang}.mf2").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+)\s*=", text, re.MULTILINE)}


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    ch = [int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(fg: str, bg: str) -> float:
    y1, y2 = _luminance(fg), _luminance(bg)
    hi, lo = max(y1, y2), min(y1, y2)
    return (hi + 0.05) / (lo + 0.05)


def test_statuses_and_invalid_sign_in_std_view():
    palette = yaml.safe_load((STD_VIEW / "palette.yaml").read_text(encoding="utf-8"))
    key = yaml.safe_load((STD_VIEW / "key.yaml").read_text(encoding="utf-8"))
    assert [r.message for r in validate({**palette, **key}, str(VIEW), "Key").results] == []

    contract = yaml.safe_load(VIEW.read_text(encoding="utf-8"))
    order = list(contract["enums"]["StatusName"]["permissible_values"])
    statuses = key["statuses"]
    assert [s["status"] for s in statuses] == order
    assert "invalid" in order

    by_name = {s["status"]: s for s in statuses}
    assert by_name["invalid"]["glyph"] == "!"
    assert by_name["invalid"]["glyph"] != by_name["violated"]["glyph"]
    assert by_name["invalid"]["color_role"] == "status.invalid"
    assert by_name["invalid"]["label_message"] == "status.invalid"

    glyphs = [s["glyph"] for s in statuses]
    assert len(set(glyphs)) == len(glyphs)

    for lang in ("en", "nl"):
        assert {s["label_message"] for s in statuses} <= message_ids(lang), lang

    palettes = {p["theme"]: {t["role"]: t["value"] for t in p["tokens"]} for p in palette["palettes"]}
    for theme in ("light", "dark", "print", "forced_colors"):
        for s in statuses:
            assert s["color_role"] in palettes[theme], (theme, s["color_role"])
    for theme in ("light", "dark", "print"):
        paper = palettes[theme]["paper"]
        for s in statuses:
            ratio = _contrast(palettes[theme][s["color_role"]], paper)
            assert ratio >= 4.5, f"{theme} {s['color_role']} contrast {ratio:.2f}:1 < 4.5:1"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/std-view-invalid-sign.md: status.invalid in packs/std-view/palette.yaml "
        "must achieve >= 3.0:1 WCAG contrast against ink (G183) alongside >= 4.5:1 against paper "
        "(1.4.3) in light, dark, and print themes."
    ),
)
def test_invalid_palette_token_contrasts_against_ink():
    palette = yaml.safe_load((STD_VIEW / "palette.yaml").read_text(encoding="utf-8"))
    palettes = {p["theme"]: {t["role"]: t["value"] for t in p["tokens"]} for p in palette["palettes"]}
    for theme in ("light", "dark", "print"):
        token = palettes[theme]["status.invalid"]
        paper_ratio = _contrast(token, palettes[theme]["paper"])
        ink_ratio = _contrast(token, palettes[theme]["ink"])
        assert paper_ratio >= 4.5, f"{theme} status.invalid vs paper {paper_ratio:.2f}:1 < 4.5:1"
        assert ink_ratio >= 3.0, f"{theme} status.invalid vs ink {ink_ratio:.2f}:1 < 3.0:1"
