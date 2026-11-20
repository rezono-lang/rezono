"""Every fact row has an origin (decisions/fact-origin-required.md). A row whose only source is its own file and
line warns W113 in a `rezono 0` pack and is refused with R053 in a `rezono 1` pack; a citation, a sidecar entry of
another kind, a `synthetic` generator and a `decide` block are origins. The expectations are copied from that
decision: one diagnostic per record and place, on one command-line line with the code and `<file>:<line>`."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from rezono_compiler import rezono_module
from rezono_compiler.__main__ import main
from support import FIXTURE, REPO

# a1 is on line 2 of its fact file; its implicit source is {kind: pack, name: facts/a.yaml, position: "2"}.
ALPHA = "alpha:\n  - {id: a1, title: open, size: 3}\n"
BETA = "beta:\n  - {id: b1, alpha: a1, state: low}\n"
TOOL = {"kind": "tool", "name": "Register scan", "position": "run 1"}
GIT = {"kind": "git", "name": "example/register", "revision": "0123abc", "position": "rows.json#/0"}
SYNTHETIC = {"kind": "synthetic", "name": "examples/sample/generate.py", "position": "seed 20261110#alpha"}
# Section 4: the sentence names every way to give a row an origin.
WAYS = ("@", "decide", "Decision", ".sources.yaml")
# The `rezono 1` module that puts a pack on rezono 1, as decisions/language-rezono-1.md section 5.8 gives it.
PANEL = {"kind": "Panel", "world": "closed", "slots": [{"slot": "active", "type": "Bool"}], "derived": []}
# A cited fact table in a dataset (decisions/language-fact-provenance.md), as test_lower_fact_provenance writes it.
CITED = {"format": "rezono.module/2", "spans": [], "module": {
    "rezono": "0", "pack": "minimal", "use": [], "decls": [{"dataset": "sample", "decls": [
        {"source": "notices", "fields": {"kind": "tool", "name": "Release notice inspection", "position": "L1"}},
        {"fact": "Alpha", "source": "notices", "columns": ["id", "title"], "sourceColumns": ["revision"], "rows": [
            [{"lit": "a-one"}, {"lit": '"One"'}, {"lit": '"19.2.0"'}],
            [{"lit": "a-two"}, {"lit": '"Two"'}, {"boundary": "omitted"}],
        ]},
    ]}],
}}
# Lines 1-7. The table row of a-one (line 5) cites nothing; the decide block (lines 6-7) sets its size.
DECIDE = ('rezono 0\npack minimal\nfact Alpha\n  | id    | title |\n  | a-one | "One" |\n'
          'decide "Size the first example alpha" by reviewer on 2026-11-20\n  a-one.size = 3\n')


class MissingOriginWarning(AssertionError):
    """A rezono 0 compile did not warn W113 as the decision gives it."""


class MissingOriginRefusal(AssertionError):
    """A rezono 1 compile did not refuse with R053 as the decision gives it."""


class MissingCitedOrigin(AssertionError):
    """A citation or a sidecar entry of a kind other than `pack` was not read as an origin, or `pack` was."""


class MissingSyntheticOrigin(AssertionError):
    """The source kind `synthetic` is not in the contract, or not read as an origin."""


class MissingDecideOrigin(AssertionError):
    """A value a `decide` block sets was not read as having an origin."""


def make_pack(tmp_path: Path, name: str, facts: dict[str, str], sidecars: dict[str, dict] | None = None) -> Path:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    (directory / "facts").mkdir()
    for file, text in facts.items():
        (directory / "facts" / file).write_text(text, encoding="utf-8")
    for file, doc in (sidecars or {}).items():
        (directory / "facts" / file).write_text(yaml.safe_dump(doc, sort_keys=True), encoding="utf-8")
    return directory


def add_module(directory: Path, stem: str, text: str, form: dict | None) -> None:
    """A module of the facts layer: its text, and its form when given (otherwise the reader writes it)."""
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    (folder / f"{stem}.rezono").write_text(text, encoding="utf-8", newline="\n")
    if form is not None:
        (folder / f"{stem}.json").write_text(json.dumps(form, sort_keys=True), encoding="utf-8")
    meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
    meta.setdefault("rezono", []).append({"module": f"rezono/{stem}.rezono", "form": f"rezono/{stem}.json",
                                          "layer": "facts"})
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")


def on_rezono_1(directory: Path) -> None:
    module = {"pack": "minimal", "use": [], "decls": [PANEL], "rezono": "1"}
    spans = [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(module)]
    add_module(directory, "panels", "rezono 1\npack minimal\n", {"format": "rezono.module/5", "module": module,
                                                                  "spans": spans})


def compiled(directory: Path, tmp_path: Path, capsys) -> tuple[int, str, list]:
    """The command's status, its standard error, and the source entries it wrote."""
    output = tmp_path / "out" / directory.parent.name
    status = main(["compile", str(directory), str(output)])
    err = capsys.readouterr().err
    path = output / "generated/sources.json"
    entries = json.loads(path.read_bytes()) if status == 0 and path.is_file() else []
    return status, err, entries


def lines(err: str, code: str) -> list[str]:
    return [line for line in err.splitlines() if code in line]


def naming(found: list[str], place: str, kind: str, identifier: str) -> list[str]:
    return [line for line in found if place in line and kind in line and identifier in line]


def test_rezono_0_warns_on_a_fact_row_without_origin(tmp_path, capsys):
    directory = make_pack(tmp_path, "warn", {"a.yaml": ALPHA, "b.yaml": BETA}, {"b.sources.yaml": {"default": TOOL}})
    status, err, entries = compiled(directory, tmp_path, capsys)
    problems = []
    if status != 0:
        problems.append(f"W113 is a warning: a rezono 0 pack with a row without origin still compiles:\n{err}")
    found = lines(err, "W113")
    named = naming(found, "facts/a.yaml:2", "alpha", "a1")
    if len(named) != 1:
        problems.append(f"expected one W113 at facts/a.yaml:2 naming alpha a1 (one per record and place): {found}")
    elif not all(way in named[0] for way in WAYS):
        problems.append(f"W113 must name every way to give an origin {WAYS}: {named[0]}")
    # Counter-case: the beta has a tool source from its sidecar.
    if any("b1" in line or "facts/b.yaml" in line for line in found):
        problems.append(f"W113 named a record whose rows have a tool source: {found}")
    # The warning changes no output: the row keeps its file and line as its locator.
    a1 = [e for e in entries if e["row"] == {"relation": "alpha", "key": '["a1"]'}]
    if status == 0 and a1 != [{"row": {"relation": "alpha", "key": '["a1"]'},
                               "sources": [{"kind": "pack", "name": "facts/a.yaml", "position": "2"}]}]:
        problems.append(f"the implicit locator of alpha a1 must stay in generated/sources.json: {a1}")
    if problems:
        raise MissingOriginWarning("\n".join(problems))


def test_rezono_1_refuses_a_fact_row_without_origin(tmp_path, capsys):
    problems = []
    refused = make_pack(tmp_path, "refused", {"a.yaml": ALPHA, "b.yaml": BETA}, {"b.sources.yaml": {"default": TOOL}})
    on_rezono_1(refused)
    status, err, _ = compiled(refused, tmp_path, capsys)
    if status == 0:
        problems.append("a rezono 1 pack compiled with a fact row whose only origin is its file and line "
                        "(expected R053)")
    else:
        found = lines(err, "R053")
        if not naming(found, "facts/a.yaml:2", "alpha", "a1"):
            problems.append(f"refused without an R053 at facts/a.yaml:2 naming alpha a1:\n{err}")
        if any("b1" in line or "facts/b.yaml" in line for line in found):
            problems.append(f"R053 named a record whose rows have a tool source: {found}")
    if "W113" in err:
        problems.append(f"a rezono 1 pack refuses with R053 and does not warn W113:\n{err}")

    # Counter-case: with an origin for every row, the same rezono 1 pack compiles.
    cited = make_pack(tmp_path, "cited", {"a.yaml": ALPHA, "b.yaml": BETA},
                      {"a.sources.yaml": {"default": TOOL}, "b.sources.yaml": {"default": TOOL}})
    on_rezono_1(cited)
    status, err, _ = compiled(cited, tmp_path, capsys)
    if status != 0 or "R053" in err:
        problems.append(f"a rezono 1 pack whose rows all have an origin must compile without R053 "
                        f"(status {status}):\n{err}")
    if problems:
        raise MissingOriginRefusal("\n".join(problems))


def test_a_citation_or_a_sidecar_entry_is_an_origin(tmp_path, capsys):
    directory = make_pack(
        tmp_path, "cited",
        {"a.yaml": ALPHA, "b.yaml": BETA,
         "c.yaml": "alpha:\n  - {id: a3, title: three}\n",
         "d.yaml": "alpha:\n  - {id: a4, title: four}\n"},
        {"b.sources.yaml": {"default": TOOL},
         "c.sources.yaml": {"default": {"kind": "pack", "name": "facts/c.yaml", "position": "2"}},
         "d.sources.yaml": {"default": GIT}})
    add_module(directory, "sample", "rezono 0\npack minimal\ndataset sample\n", CITED)
    status, err, _ = compiled(directory, tmp_path, capsys)
    problems = []
    if status != 0:
        problems.append(f"the pack must compile on rezono 0:\n{err}")
    found = lines(err, "W113")
    if not naming(found, "facts/a.yaml:2", "alpha", "a1"):
        problems.append(f"the implicit file-and-line source of alpha a1 is no origin (expected W113): {found}")
    if not naming(found, "facts/c.yaml:2", "alpha", "a3"):
        problems.append(f"a sidecar source of kind `pack` is no origin (expected W113 for alpha a3): {found}")
    for identifier, how in (("b1", "a tool sidecar"), ("a4", "a git sidecar"),
                            ("a-one", "an @ citation"), ("a-two", "an @ citation")):
        if any(identifier in line for line in found):
            problems.append(f"{how} is an origin, but W113 named {identifier}: {found}")
    if problems:
        raise MissingCitedOrigin("\n".join(problems))


def test_a_synthetic_source_is_an_origin(tmp_path, capsys):
    problems = []
    contract = yaml.safe_load((REPO / "contracts" / "source.yaml").read_text(encoding="utf-8"))
    if "synthetic" not in contract["enums"]["SourceKind"]["permissible_values"]:
        problems.append("contracts/source.yaml: SourceKind has no member `synthetic`")
    directory = make_pack(tmp_path, "synthetic", {"a.yaml": ALPHA, "s.yaml": "alpha:\n  - {id: a6, title: six}\n"},
                          {"s.sources.yaml": {"default": SYNTHETIC}})
    status, err, entries = compiled(directory, tmp_path, capsys)
    if status != 0:
        problems.append(f"a sidecar of kind `synthetic` that names its generator must load:\n{err}")
    found = lines(err, "W113")
    if not naming(found, "facts/a.yaml:2", "alpha", "a1"):
        problems.append(f"the implicit file-and-line source of alpha a1 is no origin (expected W113): {found}")
    if any("a6" in line for line in found):
        problems.append(f"a synthetic source that names its generator is an origin, but W113 named a6: {found}")
    a6 = [e["sources"] for e in entries if e["row"] == {"relation": "alpha", "key": '["a6"]'}]
    if status == 0 and a6 != [[SYNTHETIC]]:
        problems.append(f"alpha a6 must keep its synthetic source in generated/sources.json: {a6}")
    if problems:
        raise MissingSyntheticOrigin("\n".join(problems))


@pytest.mark.xfail(
    strict=True,
    raises=MissingDecideOrigin,
    reason="M3: decisions/fact-origin-required.md: Read and lower `decide \"<title>\" by <decider> on <date>` blocks "
           "(docs/rezono/v0.md section 5 and the grammar's `decide`) in a rezono 0 module, and read the values a block "
           "sets as having an origin: no W113 at the block's lines, while an uncited fact table row of the same "
           "record still warns at its own line. Read sections 1 and 4. Depends on "
           "compiler/tests/test_fact_origins.py--test_rezono_0_warns_on_a_fact_row_without_origin.",
)
def test_a_decide_block_is_an_origin(tmp_path, capsys):
    directory = make_pack(tmp_path, "decide", {})
    add_module(directory, "sample", DECIDE, None)
    source = directory / "rezono" / "sample.rezono"
    reader = subprocess.run([os.environ.get("REZONO_NODE", "node"), str(REPO / "rezono/src/write-form.ts"),
                             str(source), str(source.with_suffix(".json"))], capture_output=True, text=True)
    if reader.returncode != 0:
        raise MissingDecideOrigin(f"the reader did not read a decide block:\n{reader.stdout}{reader.stderr}")
    status, err, entries = compiled(directory, tmp_path, capsys)
    problems = []
    if status != 0:
        problems.append(f"a rezono 0 pack with a decide block must compile:\n{err}")
    found = lines(err, "W113")
    if not naming(found, "rezono/sample.rezono:5", "alpha", "a-one"):
        problems.append(f"the uncited table row of alpha a-one (line 5) has no origin (expected W113): {found}")
    if any("rezono/sample.rezono:6" in line or "rezono/sample.rezono:7" in line for line in found):
        problems.append(f"the value a decide block sets has an origin, but W113 named the block: {found}")
    if status == 0 and not any(e["row"]["relation"] == "alpha__size" and json.loads(e["row"]["key"])[0] == "a-one"
                               for e in entries):
        problems.append("the size the decide block sets is not a row of generated/sources.json")
    if problems:
        raise MissingDecideOrigin("\n".join(problems))


def test_self_citing_git_source_for_rezono_fact_module_is_no_origin(tmp_path, capsys, monkeypatch):
    from rezono_compiler import pack, sources

    def dataset_form(version: str, position: str, *, with_spans: bool = False) -> dict:
        fmt = rezono_module.REZONO_1_FORMAT if version == "1" else rezono_module.DATASET_FORMAT
        module = {
            "rezono": version,
            "pack": "minimal",
            "use": [],
            "decls": [{
                "dataset": "items",
                "decls": [
                    {
                        "source": "selfcite",
                        "fields": {
                            "kind": "git",
                            "name": "rezono-lang/rezono",
                            "revision": "deadbeef",
                            "position": position,
                        },
                    },
                    {
                        "fact": "Alpha",
                        "source": "selfcite",
                        "columns": ["id", "title"],
                        "rows": [[{"lit": "a-self"}, {"lit": '"Self"'}]],
                    },
                ],
            }],
        }
        spans = (
            [{"at": at, "line": "5", "start": "0", "end": "1"} for at in rezono_module.place_pointers(module)]
            if with_spans else []
        )
        return {"format": fmt, "spans": spans, "module": module}

    def make_rezono_pack(name: str, version: str, position: str) -> Path:
        directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
        add_module(
            directory,
            "items",
            f"rezono {version}\npack minimal\ndataset items\n",
            dataset_form(version, position),
        )
        return directory

    # Self-citations to the pack's own Rezono fact/dataset module must be rejected on rezono 1 (R053).
    for case_name, position in (
        ("v1_hash_line", "rezono/items.rezono#L5"),
        ("v1_colon_line", "rezono/items.rezono:5"),
        ("v1_repo_rel", "minimal/rezono/items.rezono#L5"),
        ("v1_json_form", "rezono/items.json#/module/decls/0/decls/1/rows/0"),
    ):
        directory = make_rezono_pack(case_name, "1", position)
        model = pack.read(directory)
        entries = sources.read(model, directory)
        missing = sources.missing_origins(model, entries, directory)
        assert missing, f"{case_name}: expected missing origin for self-citing {position!r}"
        assert missing[0].kind == "alpha" and missing[0].identifier == "a-self"
        status, err, _ = compiled(directory, tmp_path, capsys)
        assert status != 0, f"{case_name}: rezono 1 must refuse self-citing {position!r} with R053"
        assert naming(lines(err, "R053"), "rezono/items.", "alpha", "a-self"), err
        assert "W113" not in err, err

    # On rezono 0, the same self-citation warns W113 and still compiles.
    v0_dir = make_rezono_pack("v0_hash_line", "0", "rezono/items.rezono#L5")
    status, err, _ = compiled(v0_dir, tmp_path, capsys)
    assert status == 0, err
    assert naming(lines(err, "W113"), "rezono/items.rezono#L5", "alpha", "a-self"), err
    assert "R053" not in err, err

    # Authored .rezono module (not form-only) self-citing its own file is also refused with R053 on rezono 1.
    authored_dir = Path(shutil.copytree(FIXTURE, tmp_path / "authored_v1" / "minimal"))
    authored_form = dataset_form("1", "rezono/items.rezono#L5", with_spans=True)
    authored_text = (
        'rezono 1\n'
        'pack minimal\n'
        'dataset items\n'
        '  source selfcite\n'
        '    kind git\n'
        '    name "rezono-lang/rezono"\n'
        '    revision "deadbeef"\n'
        '    position "rezono/items.rezono#L5"\n'
        '  fact Alpha @ selfcite\n'
        '    | id | title |\n'
        '    | a-self | "Self" |\n'
    )
    add_module(authored_dir, "items", authored_text, authored_form)
    monkeypatch.setattr(rezono_module, "warm_pack_modules", lambda *args, **kwargs: None)
    monkeypatch.setattr(rezono_module, "warm_packs", lambda *args, **kwargs: None)
    monkeypatch.setattr(rezono_module, "authored_form", lambda *args, **kwargs: authored_form)
    status, err, _ = compiled(authored_dir, tmp_path, capsys)
    assert status != 0, "authored rezono 1 module self-citing rezono/items.rezono#L5 must fail with R053"
    assert naming(lines(err, "R053"), "rezono/items.rezono#L5", "alpha", "a-self"), err

    # Legacy YAML fact file self-citing with a :line suffix is also rejected on rezono 1.
    yaml_colon = make_pack(
        tmp_path,
        "yaml_colon",
        {"a.yaml": ALPHA},
        {"a.sources.yaml": {"default": {
            "kind": "git", "name": "rezono-lang/rezono", "revision": "deadbeef", "position": "facts/a.yaml:2",
        }}},
    )
    on_rezono_1(yaml_colon)
    status, err, _ = compiled(yaml_colon, tmp_path, capsys)
    assert status != 0, "facts/a.yaml:2 self-citation must fail with R053 on rezono 1"
    assert naming(lines(err, "R053"), "facts/a.yaml:2", "alpha", "a1"), err

    # Counter-cases: citing another file or another pack's file with the same relative path is a valid origin.
    for case_name, position in (
        ("v1_decision_doc", "decisions/fact-origin-required.md#L25"),
        ("v1_other_pack", "other-pack/rezono/items.rezono#L5"),
    ):
        directory = make_rezono_pack(case_name, "1", position)
        model = pack.read(directory)
        entries = sources.read(model, directory)
        assert sources.missing_origins(model, entries, directory) == []
        status, err, _ = compiled(directory, tmp_path, capsys)
        assert status == 0, f"{case_name}: valid external git origin {position!r} must compile:\n{err}"
        assert "R053" not in err and "W113" not in err, err


def test_own_fact_files_handles_symlinked_facts_outside_pack(tmp_path):
    from rezono_compiler import pack, sources

    directory = Path(shutil.copytree(FIXTURE, tmp_path / "linked" / "minimal"))
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "a.yaml").write_text(ALPHA, encoding="utf-8")
    (outside / "a.sources.yaml").write_text(
        yaml.safe_dump({"default": {
            "kind": "git", "name": "rezono-lang/rezono", "revision": "deadbeef", "position": "facts/a.yaml#L2",
        }}, sort_keys=True),
        encoding="utf-8",
    )
    (outside / "b.yaml").write_text(BETA, encoding="utf-8")
    (outside / "b.sources.yaml").write_text(yaml.safe_dump({"default": TOOL}, sort_keys=True), encoding="utf-8")
    facts_link = directory / "facts"
    try:
        facts_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        assert os.name == "nt"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(facts_link), str(outside)], check=True, capture_output=True)

    assert not (facts_link / "a.yaml").resolve().is_relative_to(directory.resolve())
    model = pack.read(directory)
    entries = sources.read(model, directory)
    missing = sources.missing_origins(model, entries, directory)
    assert [(item.kind, item.identifier) for item in missing] == [("alpha", "a1")]


def test_rezono_1_dataset_only_pack_sets_language_version_and_refuses_mixed_versions(tmp_path, capsys, monkeypatch):
    from rezono_compiler import emit, pack

    def make_dataset_pack(name: str, version: str, *, with_source: bool = False) -> Path:
        fmt = rezono_module.REZONO_1_FORMAT if version == "1" else rezono_module.DATASET_FORMAT
        decls: list[dict] = []
        fact_table: dict = {
            "fact": "Alpha",
            "columns": ["id", "title"],
            "rows": [[{"lit": "a-ds"}, {"lit": '"One"'}]],
        }
        if with_source:
            decls.append({"source": "notices", "fields": TOOL})
            fact_table["source"] = "notices"
        decls.append(fact_table)
        form = {
            "format": fmt,
            "spans": [],
            "module": {
                "rezono": version,
                "pack": "minimal",
                "use": [],
                "decls": [{"dataset": "items", "decls": decls}],
            },
        }
        directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
        add_module(directory, "items", f"rezono {version}\npack minimal\ndataset items\n", form)
        return directory

    # 1. A pack with schema/*.yaml + a rezono 1 dataset-only module has language_version == "1" and refuses with R053.
    ds_only = make_dataset_pack("ds_only_v1", "1", with_source=False)
    model = pack.read(ds_only)
    assert model.language_version == "1"
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    assert bundle["pack"]["language_version"] == "1"
    status, err, _ = compiled(ds_only, tmp_path, capsys)
    assert status != 0, "rezono 1 dataset-only pack with uncited fact must be refused with R053"
    assert naming(lines(err, "R053"), "rezono/items.json", "alpha", "a-ds"), err
    assert "W113" not in err, err

    # Counter-case: once every row has a valid origin, the rezono 1 dataset-only pack compiles.
    ds_cited = make_dataset_pack("ds_cited_v1", "1", with_source=True)
    assert pack.read(ds_cited).language_version == "1"
    status, err, _ = compiled(ds_cited, tmp_path, capsys)
    assert status == 0, err
    assert "R053" not in err and "W113" not in err, err

    # 2. A pack with schema/*.yaml + a rezono 1 fact-tables-only module also gets language_version == "1".
    tables_dir = Path(shutil.copytree(FIXTURE, tmp_path / "tables_only_v1" / "minimal"))
    tables_module = {
        "rezono": "1",
        "pack": "minimal",
        "use": [],
        "decls": [{"fact": "Alpha", "columns": ["id", "title"], "rows": [[{"lit": "t1"}, {"lit": '"One"'}]]}],
    }
    tables_form = {
        "format": rezono_module.REZONO_1_FORMAT,
        "module": tables_module,
        "spans": [{"at": at, "line": "5", "start": "10", "end": "15"} for at in rezono_module.place_pointers(tables_module)],
    }
    add_module(
        tables_dir,
        "items",
        'rezono 1\npack minimal\nfact Alpha\n  | id | title |\n  | t1 | "One" |\n',
        tables_form,
    )
    monkeypatch.setattr(rezono_module, "warm_pack_modules", lambda *args, **kwargs: None)
    monkeypatch.setattr(rezono_module, "warm_packs", lambda *args, **kwargs: None)
    monkeypatch.setattr(rezono_module, "authored_form", lambda *args, **kwargs: tables_form)
    assert pack.read(tables_dir).language_version == "1"

    # 3. Mixed versions: rezono 0 schema + rezono 1 dataset is refused with R027.
    mixed_s0_d1 = make_dataset_pack("mixed_s0_d1", "1", with_source=True)
    v0_schema_mod = {"rezono": "0", "pack": "minimal", "use": [], "decls": [PANEL]}
    v0_schema_form = {
        "format": rezono_module.FORMAT,
        "module": v0_schema_mod,
        "spans": [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(v0_schema_mod)],
    }
    add_module(mixed_s0_d1, "panels", "rezono 0\npack minimal\n", v0_schema_form)
    with pytest.raises(pack.CompileError, match="R027"):
        pack.read(mixed_s0_d1)

    # 4. Mixed versions: rezono 1 schema + rezono 0 dataset is refused with R027.
    mixed_s1_d0 = make_dataset_pack("mixed_s1_d0", "0", with_source=True)
    on_rezono_1(mixed_s1_d0)
    with pytest.raises(pack.CompileError, match="R027"):
        pack.read(mixed_s1_d0)

    # 5. Mixed versions: rezono 0 dataset + rezono 1 dataset (no Rezono schema modules) is refused with R027.
    mixed_d0_d1 = make_dataset_pack("mixed_d0_d1", "1", with_source=True)
    add_module(
        mixed_d0_d1,
        "extra",
        "rezono 0\npack minimal\ndataset extra\n",
        {
            "format": rezono_module.DATASET_FORMAT,
            "spans": [],
            "module": {"rezono": "0", "pack": "minimal", "use": [], "decls": [{"dataset": "extra", "decls": []}]},
        },
    )
    with pytest.raises(pack.CompileError, match="R027"):
        pack.read(mixed_d0_d1)
