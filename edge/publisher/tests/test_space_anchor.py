"""Anchoring is a view: an anchor is a derived row with its four states, its witness and its sources
(decisions/one-structure-space-and-readings.md, sections 2 and 3, red test 3).

The words of std-space this test adds to those of compiler/tests/test_theory_space.py: a kind `thing`, with a
multivalued arrow `at` to place (the places a source gives for it), and a functional derivation
`anchor(thing) -> place`, the `.one()` of those places over the things, as rows (thing, state, reason, value):
`known` with the one place, `unknown` with the reason `no_match` when no source gives a place (the type is
place, not an optional place), and `invalid` with the reason `multiple_values` when sources give two places,
with every candidate in its witness (decisions/language-rezono-1.md, set-to-functional conversion).
An invalid anchor is a finding, not a blocking check.

A neutral domain binds std-space by an ordinary view: a site is a place (`inside` is part_of) and a rack is a
thing, at the site of each sighting of it. No kind of the domain has an anchor field. Three files with three
sources: a register of sites and racks, a survey that sees r1 and r2 at h1, and a scan that sees r2 at h2.
The witness of r2's anchor is walked back to its base rows, whose sources the epoch records per row; it reaches
the survey and the scan. The epoch is the publisher's batch, which gives the rows, every witness and the
sources of the base rows.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_compiler import modules
from rezono_publisher import batch

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
SPACE = ROOT / "packs" / "std-space"


class MissingAnchorView(AssertionError):
    """No std-space to bind, or no anchor row with its four states and its witness."""


def write(path: Path, value) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")


def anchored_domain(root: Path) -> Path:
    shutil.copytree(ROOT / "packs" / "std-part", root / "std-part")
    space = Path(shutil.copytree(SPACE, root / "std-space"))
    domain = Path(shutil.copytree(MINIMAL, root / "domain"))
    write(domain / "schema" / "minimal.yaml", {
        "id": "https://rezono.example/anchored", "name": "anchored", "imports": ["linkml:types"],
        "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {
            "Site": {"attributes": {"id": {"identifier": True}, "inside": {"range": "Site"}}},
            "Rack": {"attributes": {"id": {"identifier": True}}},
            "Sighting": {"attributes": {"id": {"identifier": True}, "rack": {"range": "Rack", "required": True},
                                        "site": {"range": "Site", "required": True}}}}})
    write(domain / "pack.yaml", {"name": "anchored", "version": "0", "default_language": "nl",
                                 "imports": [{"name": "std-space", "path": "../std-space",
                                              "sha256": modules.pack_hash(space)}]})
    write(domain / "channels.yaml", {
        "kinds": [{"kind": k, "shape": "rect"} for k in ("site", "rack", "sighting")],
        "arrows": [{"arrow": a, "dash": "none"} for a in ("site.inside", "sighting.rack", "sighting.site")]})
    write(domain / "labels" / "nl.yaml", {})
    write(domain / "views.yaml", {"format": "rezono.views/1", "views": [{
        "theory": "std-space",
        "kinds": [{"name": "place", "union": [{"populated_from": "site"}]},
                  {"name": "thing", "union": [{"populated_from": "rack"}]}],
        "arrows": [{"name": "part_of", "of": "place",
                    "paths": [{"populated_from": "site", "steps": [{"slot": "inside"}]}]},
                   {"name": "at", "of": "thing",
                    "paths": [{"populated_from": "rack",
                               "steps": [{"slot": "rack", "inverse": True}, {"slot": "site"}]}]}]}]})
    facts = domain / "facts"
    facts.mkdir()
    for name, source, rows in (
            ("register", "Register", {"site": [{"id": "h1"}, {"id": "h2"}],
                                      "rack": [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}]}),
            ("survey", "Survey", {"sighting": [{"id": "s1", "rack": "r1", "site": "h1"},
                                               {"id": "s2", "rack": "r2", "site": "h1"}]}),
            ("scan", "Scan", {"sighting": [{"id": "s3", "rack": "r2", "site": "h2"}]})):
        write(facts / f"{name}.yaml", rows)
        write(facts / f"{name}.sources.yaml", {"default": {"kind": "tool", "name": source, "position": "run 1"}})
    return domain


def reached_sources(epoch, thing: str) -> set[str]:
    """The names of the sources of every base row the witnesses of `thing`'s anchor rest on."""
    by_conclusion: dict[tuple[str, str], list[dict]] = {}
    for w in epoch.witnesses:
        by_conclusion.setdefault((w["conclusion"]["relation"], w["conclusion"]["key"]), []).append(w)
    sources = {(e["row"]["relation"], e["row"]["key"]): {s["name"] for s in e["sources"]}
               for e in epoch.fact_sources or []}
    todo = [k for k in by_conclusion if k[0] == "anchor" and json.loads(k[1])[0] == thing]
    if not todo:
        raise MissingAnchorView(f"no witness concludes the anchor of {thing}")
    seen, names = set(), set()
    while todo:
        row = todo.pop()
        if row in seen:
            continue
        seen.add(row)
        if row in by_conclusion:
            todo += [(p["row"]["relation"], p["row"]["key"]) for w in by_conclusion[row] for p in w["premises"]]
        else:
            names |= sources.get(row, set())
    return names


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 3 (section 2, Anchoring is a view): "
        "waits for compiler/tests/test_theory_space.py--"
        "test_std_space_is_a_fact_free_theory_of_places_parts_and_region_relations. Then give std-space the "
        "kind thing with the arrow at and the functional derivation anchor, so that a domain bound by a view "
        "gets anchor rows that are known, unknown no_match or invalid multiple_values, with both sources in "
        "the witness of an invalid one."
    ),
)
def test_an_anchor_bound_by_a_view_has_four_states_and_both_sources_in_its_witness(tmp_path: Path):
    if not (SPACE / "pack.yaml").is_file():
        raise MissingAnchorView("packs/std-space does not exist, so no domain can bind it")
    epoch = batch.epoch(anchored_domain(tmp_path), epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                        sources=[("rules", "e1")])
    assert not [c for c in epoch.checks if c["status"] == "red"], "an invalid anchor is a finding, not a block"
    anchors = {str(r[0]): (str(r[1]), str(r[2] or ""), str(r[3]) if r[1] == "known" else "")
               for r in epoch.rows.get("anchor", [])}
    assert anchors == {"r1": ("known", "", "h1"),
                       "r2": ("invalid", "multiple_values", ""),
                       "r3": ("unknown", "no_match", "")}
    assert {"Survey", "Scan"} <= reached_sources(epoch, "r2")
    assert "Survey" in reached_sources(epoch, "r1") and "Scan" not in reached_sources(epoch, "r1")
