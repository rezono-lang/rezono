"""The library's category hierarchy as an ordinary, pinned view of std-part."""

import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import batch, facts, modules, pack, rules
from rezono_compiler.__main__ import main


ROOT = Path(__file__).resolve().parents[1]
VIEW = """format: rezono.views/1
views:
  - theory: std-part
    kinds:
      - name: constituent
        union: [{populated_from: category}]
    arrows:
      - name: part_of
        of: constituent
        paths:
          - populated_from: category
            steps: [{slot: parent}]
"""


@pytest.fixture
def library(tmp_path):
    domain = tmp_path / "library"
    shutil.copytree(ROOT / "examples/library", domain, ignore=shutil.ignore_patterns("expected"))
    theory = tmp_path / "std-part"
    shutil.copytree(ROOT / "packs/std-part", theory)
    meta = yaml.safe_load((domain / "pack.yaml").read_text())
    meta["imports"] = [{"name": "std-part", "path": "../std-part", "sha256": modules.pack_hash(theory)}]
    (domain / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    (domain / "views.yaml").write_text(VIEW, encoding="utf-8")
    return domain


def test_library_parent_supplies_the_standard_part_relations(library):
    model = pack.read(library)
    prog = rules.load(model.rules)
    valid = next(path for path in facts.files(library) if path.stem == "valid")
    rows = facts.load(model, valid)
    con, _, _ = batch.run(model, prog, rows)
    try:
        # The example's only parent is c2 -> c1. The unrelated category c3 has no whole.
        assert batch.read(con, prog, ["within", "outermost", "part_cycle"]) == {
            "within": {("c2", "c1")}, "outermost": {("c2", "c1")}, "part_cycle": set()}
    finally:
        con.close()


@pytest.mark.parametrize("old,new,reason", [
    ("slot: parent", "slot: parent, colour: blue", "unknown field 'colour'"),
    ("slot: parent", "slot: name", "views[std-part].arrows[part_of].paths[0].steps[0]: expected an arrow slot"),
    ("[{populated_from: category}]", "[{populated_from: category}, {populated_from: work}]",
     "one source kind per theory kind"),
])
def test_library_compile_refuses_invalid_theory_view_before_emitting(library, tmp_path, capsys, old, new, reason):
    (library / "views.yaml").write_text(VIEW.replace(old, new), encoding="utf-8")
    output = tmp_path / "compiled"
    assert main(["compile", str(library), str(output)]) == 1
    assert reason in capsys.readouterr().err
    assert not output.exists()
