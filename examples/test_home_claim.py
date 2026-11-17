"""A relation in a home's claim has exactly one row (docs/gui.md, The hero of a pack home; RV-V25, ruling 1,
condition 2): on the main state and in every scenario the pack ships, read from its explained goldens. The
compiler cannot see the number of rows, and the home never picks one of several, so a second row would take the
sentence off the home without a failure anywhere else. A role reads a part of these rows, so at most that
one. Generic: every example pack that declares a claim; none is named here."""

import json
from pathlib import Path

import pytest
import yaml

EXAMPLES = Path(__file__).parent


def claim(table: Path) -> list[str]:
    return ((yaml.safe_load(table.read_text("utf-8")) or {}).get("home") or {}).get("claim") or []


PACKS = sorted(p.parent for p in EXAMPLES.rglob("channels.yaml") if claim(p))


@pytest.mark.xfail(strict=True, reason="no standalone example pack declares a home claim yet")
def test_an_example_pack_declares_a_claim():
    assert PACKS


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p.name)
def test_a_claim_relation_has_one_row_in_every_state(pack):
    states = sorted(p for p in (pack / "expected" / "explained").iterdir() if p.is_dir())
    assert states
    for state in states:
        for relation in claim(pack / "channels.yaml"):
            rows = json.loads((state / "snapshots" / f"{relation}.json").read_text("utf-8"))
            assert len(rows) == 1, f"{pack.name}, {state.name}: {relation} has {len(rows)} rows"
