"""A reading is a morphism, and its losses are published: one reading report per reading and role, which
warns and never blocks (decisions/one-structure-space-and-readings.md, sections 5 and 6, red test 6).

A neutral domain binds std-space by a view, as in test_space_anchor.py: sites are places (`inside` is
part_of) and racks are things at the sites they are sighted at. It also declares a Flow of its own, `racks`,
with one lane per value of the ordered enum `tier`. So it has two readings:
- `place.places`, std-space's place layout (its default reading, read along the view): places as boxes nested
  by part_of, and each thing inside the box of its anchor. It binds no order. A thing whose anchor is not
  known has no box to stand in, so it gets no mark;
- `flow.racks`, the domain's Flow: racks in their tier lane, low before mid before high.
Two filtered roles: `viewer` reads every site, rack and sighting; `summary` reads the sites alone.

Per reading and role the manifest names a report (`readings`: reading, role, uri, sha256), in the format
`rezono.reading-report/1` with the reading, the role, the manifest and three measures. A measured measure has
`state` "measured", a `status` ("green", or "warning" with its offending elements) and the counts of the
checker's measures (rezono_checker.semiotic, semiotic_order, semiotic_coverage); an unmeasurable one has only
its `state` and the checker's `reason`. Elements are named `<kind>/<id>` in the domain's words.

The data, and the counts worked out by hand:
- sites h1, h2, and k1 inside h1; racks r1 (low), r2 (mid), r3 (high), r4 (low), with r1 feeding r3;
- sightings: r1 at k1, r2 at k1 and at h2 (its anchor is invalid), r4 at h2; r3 nowhere (unknown);
- viewer, place.places: containment k1 in h1, r1 in k1, r4 in h2: 3 of 3; coverage 3 sites and the racks r1
  and r4 of 7 elements, r2 and r3 omitted: a warning;
- viewer, flow.racks: 4 racks in their lanes; of the 6 pairs, (r1, r4) is a tie and 5 are strictly ordered;
- summary: place.places holds the 3 sites and the one part_of; flow.racks has no rack to measure.
The two omitted racks are the only offending elements: `rezono:readings` warns with 2, and the publication is
written.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_compiler import modules
from rezono_publisher import batch, publish, store

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
SPACE = ROOT / "packs" / "std-space"
ROLES = {"viewer": "may_read", "summary": "may_read"}
ACCESS = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "site", x) :- site(x).
may_read("viewer", "rack", x) :- rack(x).
may_read("viewer", "sighting", x) :- sighting(x).
may_read("summary", "site", x) :- site(x).
"""


def measured(status: str, **counts) -> dict:
    return {"state": "measured", "status": status, **counts}


def unmeasurable(reason: str) -> dict:
    return {"state": "unmeasurable", "reason": reason}


NO_ORDER = unmeasurable("ordered_enum_binding_unavailable")
EXPECTED = {
    ("place.places", "viewer"): {
        "containment": measured("green", inside=3, total=3, outside=[]),
        "order": NO_ORDER,
        "coverage": measured("warning", represented=5, total=7, omitted=["rack/r2", "rack/r3"], unexpected=[]),
    },
    ("flow.racks", "viewer"): {
        "containment": measured("green", inside=4, total=4, outside=[]),
        "order": measured("green", eligible=5, preserved=5, ties=1, unknown_pairs=0, broken=[]),
        "coverage": measured("green", represented=4, total=4, omitted=[], unexpected=[]),
    },
    ("place.places", "summary"): {
        "containment": measured("green", inside=1, total=1, outside=[]),
        "order": NO_ORDER,
        "coverage": measured("green", represented=3, total=3, omitted=[], unexpected=[]),
    },
    ("flow.racks", "summary"): {
        "containment": unmeasurable("no_containment_obligations"),
        "order": unmeasurable("no_strict_comparable_pairs"),
        "coverage": unmeasurable("no_registered_in_scope_elements"),
    },
}


class MissingReadingReport(AssertionError):
    """No std-space to read places by, or no reading report published per reading and role."""


def write(path: Path, value) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")


def domain(root: Path) -> Path:
    shutil.copytree(ROOT / "packs" / "std-part", root / "std-part")
    space = Path(shutil.copytree(SPACE, root / "std-space"))
    d = Path(shutil.copytree(MINIMAL, root / "racks"))
    write(d / "schema" / "minimal.yaml", {
        "id": "https://rezono.example/racks", "name": "racks", "imports": ["linkml:types"],
        "default_range": "string", "annotations": {"layer": "facts"},
        "enums": {"Tier": {"permissible_values": {"low": {}, "mid": {}, "high": {}}}},
        "classes": {
            "Site": {"attributes": {"id": {"identifier": True}, "inside": {"range": "Site"}}},
            "Rack": {"attributes": {"id": {"identifier": True}, "tier": {"range": "Tier", "required": True},
                                    "feeds": {"range": "Rack"}}},
            "Sighting": {"attributes": {"id": {"identifier": True}, "rack": {"range": "Rack", "required": True},
                                        "site": {"range": "Site", "required": True}}}}})
    write(d / "pack.yaml", {"name": "racks", "version": "0", "default_language": "nl",
                            "imports": [{"name": "std-space", "path": "../std-space",
                                         "sha256": modules.pack_hash(space)}]})
    write(d / "channels.yaml", {
        "kinds": [{"kind": k, "shape": "rect"} for k in ("site", "rack", "sighting")],
        "arrows": [{"arrow": a, "dash": "none"} for a in ("site.inside", "rack.feeds", "sighting.rack", "sighting.site")],
        "flows": [{"id": "racks", "title_message": "flow.racks", "direction": "right",
                   "nodes": [{"kind": "rack", "lane": {"channel": "lane", "slot": "rack.tier", "level": "ordered",
                                                       "meaning_message": "lane.tier"}}],
                   "edges": [{"arrow": "rack.feeds"}]}]})
    with (d / "messages" / "nl.mf2").open("a", encoding="utf-8", newline="\n") as messages:
        messages.write("flow.racks = {{Rekken}}\nlane.tier = {{Van laag naar hoog}}\n")
    write(d / "labels" / "nl.yaml", {})
    write(d / "views.yaml", {"format": "rezono.views/1", "views": [{
        "theory": "std-space",
        "kinds": [{"name": "place", "union": [{"populated_from": "site"}]},
                  {"name": "thing", "union": [{"populated_from": "rack"}]}],
        "arrows": [{"name": "part_of", "of": "place",
                    "paths": [{"populated_from": "site", "steps": [{"slot": "inside"}]}]},
                   {"name": "at", "of": "thing",
                    "paths": [{"populated_from": "rack",
                               "steps": [{"slot": "rack", "inverse": True}, {"slot": "site"}]}]}]}]})
    (d / "facts").mkdir()
    write(d / "facts" / "racks.yaml", {
        "site": [{"id": "h1"}, {"id": "h2"}, {"id": "k1", "inside": "h1"}],
        "rack": [{"id": "r1", "tier": "low", "feeds": "r3"}, {"id": "r2", "tier": "mid"},
                 {"id": "r3", "tier": "high"}, {"id": "r4", "tier": "low"}],
        "sighting": [{"id": "s1", "rack": "r1", "site": "k1"}, {"id": "s2", "rack": "r2", "site": "k1"},
                     {"id": "s3", "rack": "r2", "site": "h2"}, {"id": "s4", "rack": "r4", "site": "h2"}]})
    write(d / "facts" / "racks.sources.yaml", {"default": {"kind": "tool", "name": "Survey", "position": "run 1"}})
    (d / "rules").mkdir()
    (d / "rules" / "access.dl").write_text(ACCESS, encoding="utf-8", newline="\n")
    return d


def key_of(uri: str) -> str:
    return uri.split("://", 1)[1].split("/", 1)[1] if "://" in uri else uri


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 6 (section 5, A reading is a "
        "morphism, and its losses are published): waits for edge/publisher/tests/test_space_anchor.py--"
        "test_an_anchor_bound_by_a_view_has_four_states_and_both_sources_in_its_witness and "
        "compiler/tests/test_theory_default_reading.py--"
        "test_a_domain_bound_to_std_part_without_channels_gets_the_flow_of_parts. Then give std-space the place "
        "layout place.places, and let the publisher publish a rezono.reading-report/1 per reading and role with "
        "the checker's containment, order and coverage, where a broken obligation is a warning and never blocks."
    ),
)
def test_a_reading_report_per_reading_and_role_warns_and_does_not_block(tmp_path: Path):
    if not (SPACE / "pack.yaml").is_file():
        raise MissingReadingReport("packs/std-space does not exist, so there is no place layout to report on")
    st = store.FileStore(tmp_path / "store")
    ep = batch.epoch(domain(tmp_path), epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "e1")])
    manifest = publish.publish(ep, st, ROLES)  # a broken obligation does not raise Blocked
    assert st.get(f"{ep.pack}/manifests/{manifest['id']}.json") is not None, "the publication is written"
    if "readings" not in manifest:
        raise MissingReadingReport(f"the manifest names no reading report: {sorted(manifest)}")
    entries = {(e["reading"], e["role"]): e for e in manifest["readings"]}
    assert set(entries) == set(EXPECTED)
    for (reading, role), entry in sorted(entries.items()):
        body = st.get(key_of(entry["uri"]))
        assert body is not None and hashlib.sha256(body).hexdigest() == entry["sha256"], (reading, role)
        report = json.loads(body)
        assert {k: report.get(k) for k in ("format", "reading", "role", "manifest")} == {
            "format": "rezono.reading-report/1", "reading": reading, "role": role, "manifest": manifest["id"]}
        assert report["measures"] == EXPECTED[(reading, role)], (reading, role)
    assert {"name": "rezono:readings", "status": "warning", "violations": 2} in manifest["checks"]
