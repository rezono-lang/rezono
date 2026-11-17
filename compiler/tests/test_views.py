"""Closed view definitions are readable/hashable; outside the profile that executes (RV-C27) they are refused."""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import emit, modules, pack, views

FIXTURES = Path(__file__).parent / "fixtures"
STRUCTURAL = FIXTURES / "views" / "structural.yaml"


def fixture():
    return yaml.safe_load(STRUCTURAL.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def replace(doc, key, value):
    for part in key[:-1]:
        doc = doc[part]
    doc[key[-1]] = value


def test_closed_structural_readback_and_deterministic_order(tmp_path):
    path = write(tmp_path / "views.yaml", fixture())
    got = views.read(path)
    spec = got.views[0]
    assert spec.theory == "std-structure"
    assert [b.populated_from for b in spec.kinds[0].union] == ["alpha", "beta"]
    assert spec.arrows[0].paths[0].steps[0] == views.ViewStep("from", True)
    doc = views.document(got)
    assert views.read(write(path, doc)) == got
    assert json.dumps(views.document(views.read(path)), sort_keys=True) == json.dumps(doc, sort_keys=True)
    changed = fixture()
    changed["views"][0]["kinds"][0]["union"].reverse()
    changed["views"][0]["arrows"][0]["paths"].reverse()
    assert views.read(write(path, changed)) == got
    # A path is ordered, even though the alternative branches are not.
    changed = fixture()
    changed["views"][0]["arrows"][0]["paths"][0]["steps"].reverse()
    assert views.read(write(path, changed)) != got


@pytest.mark.parametrize("key", [(), ("views", 0), ("views", 0, "kinds", 0),
    ("views", 0, "kinds", 0, "union", 0), ("views", 0, "arrows", 0),
    ("views", 0, "arrows", 0, "paths", 0), ("views", 0, "arrows", 0, "paths", 0, "steps", 0)])
def test_unknown_fields_are_refused_at_every_level(tmp_path, key):
    doc = fixture()
    target = doc
    for part in key:
        target = target[part]
    target["unexpected"] = "not ignored"
    with pytest.raises(views.ViewError, match="views.yaml: .*unknown field 'unexpected'"):
        views.read(write(tmp_path / "views.yaml", doc))


@pytest.mark.parametrize("key", [("views",), ("views", 0, "kinds"),
    ("views", 0, "kinds", 0, "union"), ("views", 0, "arrows", 0, "paths"),
    ("views", 0, "arrows", 0, "paths", 0, "steps")])
def test_required_collections_are_nonempty_lists(tmp_path, key):
    for value in ([], {}, None, "alpha"):
        doc = fixture(); replace(doc, key, value)
        with pytest.raises(views.ViewError, match="expected a non-empty list"):
            views.read(write(tmp_path / "views.yaml", doc))


@pytest.mark.parametrize("key", [("views", 0, "arrows", 0, "assume_functional"),
    ("views", 0, "arrows", 0, "paths", 0, "steps", 0, "inverse")])
@pytest.mark.parametrize("value", ["true", "false", 0, 1, None])
def test_boolean_declarations_are_strict(tmp_path, key, value):
    doc = fixture(); replace(doc, key, value)
    with pytest.raises(views.ViewError, match="expected a boolean"):
        views.read(write(tmp_path / "views.yaml", doc))


@pytest.mark.parametrize("key", [("views",), ("views", 0, "kinds"),
    ("views", 0, "kinds", 0, "union"), ("views", 0, "arrows"),
    ("views", 0, "arrows", 0, "paths")])
def test_duplicate_declarations_do_not_pick_a_branch(tmp_path, key):
    doc = fixture(); target = doc
    for part in key:
        target = target[part]
    target.append(copy.deepcopy(target[0]))
    with pytest.raises(views.ViewError, match="duplicate declaration"):
        views.read(write(tmp_path / "views.yaml", doc))


def test_duplicate_yaml_field_is_not_silently_overridden(tmp_path):
    path = tmp_path / "views.yaml"
    path.write_text("format: rede.views/1\nformat: ignored\nviews: []\n", encoding="utf-8")
    with pytest.raises(views.ViewError, match="duplicate field 'format'"):
        views.read(path)


def test_source_union_is_explicit_not_list_valued_populated_from(tmp_path):
    doc = fixture()
    doc["views"][0]["kinds"][0]["union"][0]["populated_from"] = ["alpha", "beta"]
    with pytest.raises(views.ViewError, match="populated_from: expected a valid name"):
        views.read(write(tmp_path / "views.yaml", doc))


def test_source_slot_component_is_not_its_engine_table(tmp_path):
    # The real existing source fixture distinguishes Slot.name from Slot.table.
    model = pack.read(FIXTURES / "minimal")
    slot = model.slot("beta", "alpha")
    assert slot.arrow and slot.name == "alpha" and slot.table == "beta__alpha"
    doc = fixture()
    path = doc["views"][0]["arrows"][0]["paths"][0]
    path.update(populated_from="beta", steps=[{"slot": slot.name}])
    parsed = views.read(write(tmp_path / "views.yaml", doc))
    assert any(p.steps == (views.ViewStep("alpha"),) for p in parsed.views[0].arrows[0].paths)
    path["steps"][0]["slot"] = slot.table
    with pytest.raises(views.ViewError, match="slot: expected a valid name"):
        views.read(write(tmp_path / "views.yaml", doc))


@pytest.mark.parametrize("raw_name", ["Module#Alpha", "shared:terms", "alpha.first"])
def test_unresolved_schema_module_names_are_outside_this_profile(tmp_path, raw_name):
    doc = fixture()
    doc["views"][0]["kinds"][0]["union"][0]["populated_from"] = raw_name
    with pytest.raises(views.ViewError, match="populated_from: expected a valid name"):
        views.read(write(tmp_path / "views.yaml", doc))


def test_expr_is_not_executed_or_accepted_as_structural_data(tmp_path):
    doc = fixture(); marker = tmp_path / "should-not-exist"
    doc["views"][0]["arrows"][0]["paths"][0]["expr"] = f"__import__('pathlib').Path({str(marker)!r}).touch()"
    with pytest.raises(views.ViewError, match="unknown field 'expr'"):
        views.read(write(tmp_path / "views.yaml", doc))
    assert not marker.exists()


@pytest.mark.parametrize("body", ["", "[]", "format: wrong\nviews: []", "format: [rede.views/1]\nviews: []", "format: rede.views/1\nviews: ["])
def test_invalid_document_is_not_an_absent_view(tmp_path, body):
    path = tmp_path / "views.yaml"; path.write_text(body, encoding="utf-8")
    with pytest.raises(views.ViewError, match="views.yaml:"):
        views.read(path)


def source_pack(tmp_path, where):
    target = Path(shutil.copytree(FIXTURES / "minimal", tmp_path / "main"))
    owner = target
    if where == "import":
        owner = Path(shutil.copytree(FIXTURES / "shared", tmp_path / "shared"))
    write(owner / "views.yaml", fixture())
    if where == "import":
        meta = yaml.safe_load((target / "pack.yaml").read_text(encoding="utf-8"))
        meta["imports"] = [{"name": "shared-terms", "path": "../shared", "sha256": modules.pack_hash(owner)}]
        write(target / "pack.yaml", meta)
    return target, owner


@pytest.mark.parametrize("where", ["main", "import"])
def test_pack_and_source_publication_refuse_valid_unlowered_views(tmp_path, monkeypatch, where):
    target, _ = source_pack(tmp_path, where)
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported view reached compiler/DB execution")
    monkeypatch.setattr(emit, "compile_pack", forbidden)
    with pytest.raises(pack.CompileError, match=r"views.yaml: .*view execution is not supported (for|here)"):
        pack.read(target)
    import duckdb
    from rezono_publisher.batch import epoch
    monkeypatch.setattr(duckdb, "connect", forbidden)
    with pytest.raises(pack.CompileError, match=r"views.yaml: .*view execution is not supported (for|here)"):
        epoch(target, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])


def test_metadata_boundary_also_refuses_the_main_view_file(tmp_path):
    target, _ = source_pack(tmp_path, "main")
    with pytest.raises(pack.CompileError, match="view execution is not supported for"):
        pack.read_meta(target)


def test_view_bytes_change_definition_and_import_pins(tmp_path):
    target = Path(shutil.copytree(FIXTURES / "minimal", tmp_path / "main"))
    from rezono_publisher.batch import definition_sha256
    old = modules.pack_hash(target), definition_sha256(target)
    path = write(target / "views.yaml", fixture())
    new = modules.pack_hash(target), definition_sha256(target)
    assert old[0] != new[0] and old[1] != new[1]
    assert path in modules.definition_files(target)
    path.write_text(path.read_text(encoding="utf-8") + "# source bytes matter\n", encoding="utf-8")
    assert modules.pack_hash(target) != new[0]


def test_changed_import_view_invalidates_existing_pin(tmp_path):
    target, owner = source_pack(tmp_path, "import")
    path = owner / "views.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    with pytest.raises(pack.CompileError, match="hash"):
        pack.read(target)
