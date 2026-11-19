"""A `use` line with a prefix must make a pinned pack's kinds visible under that prefix only, and lower as the
same `use` line without one does (decisions/language-imports.md, section Lowering a prefix). The oracle is the
schema file the unprefixed lowering is already compared with in test_lower_module_import."""

import json
from pathlib import Path

import pytest
import yaml

from support import compile_dir
from test_lower_module_import import HOLDER, meaning, pinned
from test_rezono_module import module
from rezono_compiler import pack


def prefixed(d: Path, slot_type: str) -> None:
    """The module holder with `use lib as terms` on line 3 and the slot `party: <slot_type>` on line 11."""
    module(d, [HOLDER | {"slots": [{"slot": "party", "type": slot_type}]}], use=["lib"], name="holder")
    path = d / "rezono" / "holder.json"
    form = json.loads(path.read_bytes())
    form["module"]["use"] = [{"use": "lib", "as": "terms"}]
    path.write_bytes(json.dumps(form, sort_keys=True).encode("utf-8"))


class MissingPrefixedImport(AssertionError):
    """The compiler refused a `use` line with a prefix, which decisions/language-imports.md lowers."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingPrefixedImport,
    reason="extra: decisions/language-imports.md: Lower a use line with a prefix (use lib as terms) and a slot type "
           "terms.Party as the same use line without the prefix and the type Party, in "
           "compiler/rezono_compiler/rezono_module.py instead of the refusal of a prefix; refuse at the slot a "
           "prefix that no use line declares and a prefixed name the pack does not declare, and keep refusing a "
           "dotted pack name. Read the section Lowering a prefix.",
)
def test_lower_prefixed_import(tmp_path):
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
    prefixed(candidate, "terms.Party")
    try:
        actual = json.loads(compile_dir(candidate, tmp_path / "candidate-out")["bundle/schema-bundle.json"])
    except pack.CompileError as refused:
        raise MissingPrefixedImport(str(refused)) from refused
    assert meaning(actual) == expected

    # Counter-cases, each refused at the slot on line 11: the bare name of a prefixed pack, a prefix that no use
    # line declares, and a prefixed name the pack does not declare.
    for how, slot_type in (("bare", "Party"), ("stray", "other.Party"), ("absent", "terms.Partner")):
        d = pinned(tmp_path, how)
        prefixed(d, slot_type)
        with pytest.raises(pack.CompileError, match=r"main/rezono/holder\.rezono:11: "):
            pack.read(d)
