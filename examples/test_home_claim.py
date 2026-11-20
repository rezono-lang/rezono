"""A relation in a home's claim has exactly one row (decisions/language-subsidy-home.md; decisions/viewer-slip.md, The sentence): on the main state and in every scenario the pack ships, read from its explained snapshots. The
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


def test_an_example_pack_declares_a_claim():
    assert PACKS


@pytest.mark.parametrize("pack", PACKS, ids=lambda p: p.name)
def test_a_claim_relation_has_one_row_in_every_state(pack):
    from rezono_compiler import facts
    from rezono_compiler import pack as packs
    from rezono_compiler.__main__ import explained

    snapshots = explained(packs.read(pack), pack)
    # Enumerate the inputs independently so a missing output state fails this check.
    inputs = facts.files(pack)
    states = ([f"0-{inputs[0].stem}"] if inputs else []) + [
        scenario.stem for scenario in sorted((pack / "scenarios").glob("*.yaml"))
    ]
    assert states
    relations = claim(pack / "channels.yaml")
    for state in states:
        for relation in relations:
            path = f"{state}/snapshots/{relation}.json"
            assert path in snapshots, f"{pack.name} has no {path}"
            rows = json.loads(snapshots[path])
            assert len(rows) == 1, f"{pack.name}, {state}: {relation} has {len(rows)} rows"
