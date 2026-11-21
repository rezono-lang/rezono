"""The key of signs from std-view, published in every schema bundle (decisions/release-1-scope.md section 4)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from .pack import CONTRACTS, entries

PARTS = ("statuses", "tones", "signs", "differences")

# Embedded snapshot of packs/std-view/key.yaml and packs/std-view/messages/*.mf2 for installations
# outside a repository checkout (for example a wheel or a kept replay archive).
FALLBACK_KEY: dict[str, tuple[dict, ...]] = {
    "statuses": (
        {"status": "valid", "tone": "positive", "color_role": "status.valid", "glyph": "✓", "label_message": "status.valid"},
        {"status": "changed", "tone": "caution", "color_role": "status.changed", "glyph": "◐", "label_message": "status.changed"},
        {"status": "violated", "tone": "negative", "color_role": "status.violated", "glyph": "✕", "label_message": "status.violated"},
        {"status": "unknown", "tone": "unknown", "color_role": "status.unknown", "glyph": "▨", "label_message": "status.unknown", "hatched": True},
        {"status": "not_applicable", "tone": "neutral", "color_role": "status.not_applicable", "glyph": "–", "label_message": "status.not_applicable"},
        {"status": "absent", "tone": "neutral", "color_role": "status.not_applicable", "glyph": "⦸", "label_message": "status.absent"},
    ),
    "tones": (
        {"tone": "positive", "color_role": "status.valid", "glyph": "✓", "label_message": "tone.positive"},
        {"tone": "neutral", "color_role": "status.not_applicable", "glyph": "–", "label_message": "tone.neutral"},
        {"tone": "caution", "color_role": "status.changed", "glyph": "◐", "label_message": "tone.caution"},
        {"tone": "negative", "color_role": "status.violated", "glyph": "✕", "label_message": "tone.negative"},
        {"tone": "unknown", "color_role": "status.unknown", "glyph": "▨", "label_message": "tone.unknown"},
    ),
    "signs": (
        {"sign": "origin_decision", "form": "glyph", "glyph": "◆", "label_message": "sign.origin_decision"},
        {"sign": "origin_vendor", "form": "glyph", "glyph": "▲", "label_message": "sign.origin_vendor"},
        {"sign": "origin_design", "form": "glyph", "glyph": "■", "label_message": "sign.origin_design"},
        {"sign": "origin_observation", "form": "glyph", "glyph": "●", "label_message": "sign.origin_observation"},
        {"sign": "derived", "form": "glyph", "glyph": "○", "label_message": "sign.derived"},
        {"sign": "assumption", "form": "underline", "dash": "4 3", "label_message": "sign.assumption"},
        {"sign": "drift", "form": "double_line", "tone": "caution", "dash": "6 3", "label_message": "sign.drift"},
        {"sign": "screened", "form": "bar", "label_message": "sign.screened"},
        {"sign": "proposal", "form": "frame", "glyph": "✎", "dash": "4 3", "label_message": "sign.proposal"},
        {"sign": "sealed", "form": "stamp", "label_message": "sign.sealed"},
        {"sign": "supposed", "form": "replaced", "accent": True, "label_message": "sign.supposed"},
    ),
    "differences": (
        {"change": "added", "glyph": "+", "tone": "caution", "label_message": "impact.added"},
        {"change": "removed", "glyph": "−", "tone": "caution", "label_message": "impact.removed"},
        {"change": "changed", "glyph": "Δ", "tone": "caution", "label_message": "impact.changed"},
    ),
}

FALLBACK_MESSAGES: dict[str, tuple[tuple[str, str], ...]] = {
    "en": (
        ("status.valid", "status.valid = valid\n"),
        ("status.changed", "status.changed = changed\n"),
        ("status.violated", "status.violated = violated\n"),
        ("status.unknown", "status.unknown = unknown\n"),
        ("status.not_applicable", "status.not_applicable = not applicable\n"),
        ("status.absent", "status.absent = absent, checked\n"),
        ("tone.positive", "tone.positive = positive\n"),
        ("tone.neutral", "tone.neutral = neutral\n"),
        ("tone.caution", "tone.caution = caution\n"),
        ("tone.negative", "tone.negative = negative\n"),
        ("tone.unknown", "tone.unknown = unknown\n"),
        ("sign.origin_decision", "sign.origin_decision = origin: decision\n"),
        ("sign.origin_vendor", "sign.origin_vendor = origin: vendor or law\n"),
        ("sign.origin_design", "sign.origin_design = origin: design\n"),
        ("sign.origin_observation", "sign.origin_observation = origin: observation\n"),
        ("sign.derived", "sign.derived = derived\n"),
        ("sign.assumption", "sign.assumption = assumption\n"),
        ("sign.drift", "sign.drift = differs from the reference\n"),
        ("sign.screened", "sign.screened = not visible to your role\n"),
        ("sign.proposal", "sign.proposal = proposal\n"),
        ("sign.sealed", "sign.sealed = sealed\n"),
        ("sign.supposed", "sign.supposed = supposed\n"),
        ("impact.added", "impact.added = added\n"),
        ("impact.removed", "impact.removed = removed\n"),
        ("impact.changed", "impact.changed = changed\n"),
    ),
    "nl": (
        ("status.valid", "status.valid = geldend\n"),
        ("status.changed", "status.changed = gewijzigd\n"),
        ("status.violated", "status.violated = geschonden\n"),
        ("status.unknown", "status.unknown = onbekend\n"),
        ("status.not_applicable", "status.not_applicable = niet van toepassing\n"),
        ("status.absent", "status.absent = afwezig, gecontroleerd\n"),
        ("tone.positive", "tone.positive = positief\n"),
        ("tone.neutral", "tone.neutral = neutraal\n"),
        ("tone.caution", "tone.caution = let op\n"),
        ("tone.negative", "tone.negative = negatief\n"),
        ("tone.unknown", "tone.unknown = onbekend\n"),
        ("sign.origin_decision", "sign.origin_decision = herkomst: besluit\n"),
        ("sign.origin_vendor", "sign.origin_vendor = herkomst: leverancier of wet\n"),
        ("sign.origin_design", "sign.origin_design = herkomst: ontwerp\n"),
        ("sign.origin_observation", "sign.origin_observation = herkomst: waarneming\n"),
        ("sign.derived", "sign.derived = afgeleid\n"),
        ("sign.assumption", "sign.assumption = aanname\n"),
        ("sign.drift", "sign.drift = wijkt af van de referentie\n"),
        ("sign.screened", "sign.screened = niet zichtbaar voor je rol\n"),
        ("sign.proposal", "sign.proposal = voorstel\n"),
        ("sign.sealed", "sign.sealed = verzegeld\n"),
        ("sign.supposed", "sign.supposed = verondersteld\n"),
        ("impact.added", "impact.added = erbij\n"),
        ("impact.removed", "impact.removed = eraf\n"),
        ("impact.changed", "impact.changed = anders\n"),
    ),
}


@cache
def _load_from_dir(std_view: Path) -> tuple[dict[str, list[dict]], dict[str, tuple[tuple[str, str], ...]]]:
    raw = yaml.safe_load((std_view / "key.yaml").read_text(encoding="utf-8"))
    key = {part: list(raw[part]) for part in PARTS}
    labels = {item["label_message"] for part in PARTS for item in key[part]}
    messages: dict[str, tuple[tuple[str, str], ...]] = {}
    for path in sorted((std_view / "messages").glob("*.mf2")):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        _, _, body = text.partition("\n---\n")
        messages[path.stem] = tuple(
            (mid, block.rstrip("\n") + "\n") for mid, block in entries(body) if mid in labels
        )
    return key, messages


def load(std_view: Path | None = None) -> tuple[dict[str, list[dict]], dict[str, tuple[tuple[str, str], ...]]]:
    """Return the key of signs and its label messages per language from std-view (or the bundled snapshot)."""
    target = std_view if std_view is not None else CONTRACTS.parent / "packs" / "std-view"
    if (target / "key.yaml").is_file() and (target / "messages").is_dir():
        return _load_from_dir(target)
    return {part: [dict(entry) for entry in rows] for part, rows in FALLBACK_KEY.items()}, FALLBACK_MESSAGES


def merge_messages(
    pack_messages: dict[str, str],
    key_messages: dict[str, tuple[tuple[str, str], ...]],
) -> list[dict[str, str]]:
    """Merge the key-of-signs label messages into the pack's MF2 resources without duplicates or losses."""
    out: list[dict[str, str]] = []
    for lang in sorted(set(pack_messages) | set(key_messages)):
        text = pack_messages.get(lang, "").replace("\r\n", "\n")
        add = key_messages.get(lang, ())
        if not text:
            resource = f"@locale {lang}\n---\n" + "".join(block for _, block in add)
        elif not add:
            resource = text
        else:
            head, sep, body = text.partition("\n---\n")
            if not sep:
                head, body = f"@locale {lang}", text
            own = {mid for mid, _ in entries(body)}
            prefix = "".join(block for mid, block in add if mid not in own)
            resource = f"{head}\n---\n{prefix}{body}"
        out.append({"lang": lang, "resource": resource})
    return out
