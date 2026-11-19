"""The verb bar of std-view (decisions/viewer-slip.md, "The verbs"): packs/std-view/sheets.yaml validates against
`Sheets` in contracts/view.yaml, with the six verbs of `VerbName` in the contract's order, each once, each with a
key of its own, and each label a message in English and in Dutch. The oracle is the contract, not the file."""

import re
from pathlib import Path

import yaml
from linkml.validator import validate

ROOT = Path(__file__).resolve().parents[3]
VIEW = ROOT / "contracts" / "view.yaml"
STD_VIEW = ROOT / "packs" / "std-view"


def message_ids(lang: str) -> set[str]:
    text = (STD_VIEW / "messages" / f"{lang}.mf2").read_text(encoding="utf-8")
    return {m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+)\s*=", text, re.MULTILINE)}


def test_verb_bar_in_std_view():
    sheets = yaml.safe_load((STD_VIEW / "sheets.yaml").read_text(encoding="utf-8"))
    assert [r.message for r in validate(sheets, str(VIEW), "Sheets").results] == []
    contract = yaml.safe_load(VIEW.read_text(encoding="utf-8"))
    order = list(contract["enums"]["VerbName"]["permissible_values"])
    verbs = sheets["verbs"]
    assert [verb["verb"] for verb in verbs] == order
    keys = [verb["key"] for verb in verbs]
    assert len(set(keys)) == len(keys) == 6
    for lang in ("en", "nl"):
        assert {verb["label_message"] for verb in verbs} <= message_ids(lang), lang
