"""A `use` line must make a pinned pack's kinds visible, as the LinkML import of its schema module does."""

import json
from pathlib import Path
import shutil

import pytest
import yaml

from support import FIXTURE, compile_dir
from test_rezono_module import add, module
from rezono_compiler import modules, pack


SHARED = FIXTURE.parent / "shared"
HOLDER = {"kind": "Holder", "world": "closed", "slots": [{"slot": "party", "type": "Party"}], "derived": []}


def pinned(tmp_path: Path, how: str) -> Path:
    """The fixture pack beside a pack `lib` that it pins; `lib` declares the kind Party in its module `terms`."""
    lib = Path(shutil.copytree(SHARED, tmp_path / how / "lib"))
    meta = yaml.safe_load((lib / "pack.yaml").read_bytes())
    (lib / "pack.yaml").write_bytes(yaml.safe_dump(dict(meta, name="lib"), sort_keys=False).encode("utf-8"))
    d = Path(shutil.copytree(FIXTURE, tmp_path / how / "main"))
    meta = yaml.safe_load((d / "pack.yaml").read_bytes())
    meta["imports"] = [{"name": "lib", "path": "../lib", "sha256": modules.pack_hash(lib)}]
    (d / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
    add(d / "labels" / "nl.yaml", "holder: houder\nholder.party: partij\n")
    return d


def meaning(bundle: dict) -> dict:
    """What the bundle says about the kind Holder: its arrows and the imported module it reads."""
    return {
        "kinds": sorted(k["id"] for k in bundle["kinds"]),
        "arrows": sorted((a["id"], a["target"], a["required"]) for a in bundle["arrows"]),
        "imported": sorted(s["module"] for s in bundle["schemas"] if s["module"].startswith("lib:")),
    }


@pytest.mark.xfail(
    strict=True,
    raises=pack.CompileError,
    reason="Resolve an unaliased use line of a schema module against the packs that pack.yaml pins, and add the "
           "LinkML import of each schema module of the used pack, in compiler/rezono_compiler/rezono_module.py "
           "(header_errors and lower). Refuse a use of a pack that is not pinned at its line. Read "
           "decisions/language-imports.md. Remove the case 'use' from the header refusals in "
           "compiler/tests/test_rezono_module.py, which this task may change. No reader dependency.",
)
def test_lower_module_import(tmp_path):
    legacy = pinned(tmp_path, "legacy")
    (legacy / "schema" / "holder.yaml").write_bytes(yaml.safe_dump({
        "id": "https://rezono.example/holder", "name": "holder", "imports": ["linkml:types", "lib:terms"],
        "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {"Holder": {"attributes": {"id": {"identifier": True},
                                              "party": {"range": "Party", "required": True}}}},
    }, sort_keys=False).encode("utf-8"))
    expected = meaning(json.loads(compile_dir(legacy, tmp_path / "legacy-out")["bundle/schema-bundle.json"]))
    assert ("holder.party", "party", True) in expected["arrows"]

    candidate = pinned(tmp_path, "candidate")
    module(candidate, [HOLDER], use=["lib"], name="holder")
    actual = json.loads(compile_dir(candidate, tmp_path / "candidate-out")["bundle/schema-bundle.json"])
    assert meaning(actual) == expected

    # Counter-case: without the use line the kind of the pinned pack is not visible.
    hidden = pinned(tmp_path, "hidden")
    module(hidden, [HOLDER], name="holder")
    with pytest.raises(pack.CompileError, match=r"main/rezono/holder\.rezono:11: Party is not"):
        pack.read(hidden)

    # Counter-case: a use line must name a pack that pack.yaml pins.
    stray = pinned(tmp_path, "stray")
    module(stray, [HOLDER], use=["lib", "other"], name="holder")
    with pytest.raises(pack.CompileError, match=r"main/rezono/holder\.rezono:4: .*other"):
        pack.read(stray)
