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


@pytest.mark.xfail(
    strict=True,
    raises=MissingSyntheticOrigin,
    reason="M3: decisions/fact-origin-required.md: Add `synthetic` to SourceKind in contracts/source.yaml (name the "
           "generator, position the seed and part) and to KINDS in checker/rezono_checker/sources.py, and read a "
           "synthetic source as an origin. Read section 3. Depends on "
           "compiler/tests/test_fact_origins.py--test_rezono_0_warns_on_a_fact_row_without_origin.",
)
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
