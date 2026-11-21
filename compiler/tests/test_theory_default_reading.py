"""A theory's channels give its default readings to every domain bound to it
(decisions/one-structure-space-and-readings.md, section 7 and red test 7).

A neutral domain binds std-part by a view: its kind `unit` is a constituent and its arrow `unit.housed_in` is
part_of. It has labels and no channels of its own. Its compiled bundle then carries std-part's Flow of parts as
its reading, read along the view: the nodes are the domain's units and the lines its housed_in arrow, so that
the Flow draws the domain's own rows. The signs of unit and housed_in are std-part's signs of constituent and
part_of. The expected Flow is std-part's channels.yaml with the view's two words put in.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from rezono_compiler import emit, modules, pack

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures/minimal"


class NoDefaultReading(AssertionError):
    """A domain bound to std-part without channels of its own does not get the Flow of parts."""


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8", newline="\n")


def domain_without_channels(root):
    theory = Path(shutil.copytree(REPO / "packs" / "std-part", root / "std-part"))
    domain = Path(shutil.copytree(FIXTURE, root / "domain"))
    write(domain / "schema/minimal.yaml", {
        "id": "https://rezono.example/bound-to-std-part", "name": "domain", "imports": ["linkml:types"],
        "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {"Unit": {"attributes": {"id": {"identifier": True}, "housed_in": {"range": "Unit"}}}}})
    write(domain / "pack.yaml", {"name": "domain", "version": "0", "default_language": "nl",
                                 "imports": [{"name": "std-part", "path": "../std-part",
                                              "sha256": modules.pack_hash(theory)}]})
    (domain / "channels.yaml").unlink()
    write(domain / "labels/nl.yaml", {"unit": "eenheid", "unit.housed_in": "staat in"})
    write(domain / "views.yaml", {"format": "rezono.views/1", "views": [{
        "theory": "std-part",
        "kinds": [{"name": "constituent", "union": [{"populated_from": "unit"}]}],
        "arrows": [{"name": "part_of", "of": "constituent",
                    "paths": [{"populated_from": "unit", "steps": [{"slot": "housed_in"}]}]}]}]})
    return domain


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 7 (section 7, The theory chooses the "
        "form): compile a domain bound to std-part that has no channels.yaml, and give its bundle std-part's "
        "Flow of parts read along the view (nodes unit, lines unit.housed_in) with std-part's signs."
    ),
)
def test_a_domain_bound_to_std_part_without_channels_gets_the_flow_of_parts(tmp_path):
    domain = domain_without_channels(tmp_path)
    try:
        files = emit.compile_pack(pack.read(domain))
    except pack.CompileError as err:
        raise NoDefaultReading(f"the bound domain without channels does not compile: {err}") from None
    channels = json.loads(files["bundle/schema-bundle.json"]).get("channels", {})
    assert channels.get("flows") == [{"id": "parts", "title_message": "flow.parts", "direction": "right",
                                      "nodes": [{"kind": "unit"}], "edges": [{"arrow": "unit.housed_in"}]}]
    assert {"kind": "unit", "shape": "rect"} in channels.get("kinds", [])
    assert {"arrow": "unit.housed_in", "dash": "none"} in channels.get("arrows", [])
