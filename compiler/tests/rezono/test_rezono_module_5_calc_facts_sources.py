"""Counterexample tests for rezono.module/5 support in calculations, facts, and sources."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import emit, facts, pack, rezono_calc, rezono_module, sources
from rezono_compiler.__main__ import main
from support import FIXTURE


def _form(fmt: str, module: dict, *, line: str = "1", start: str = "0", end: str = "1") -> dict:
    spans = [{"at": at, "line": line, "start": start, "end": end} for at in rezono_module.place_pointers(module)]
    return {"format": fmt, "module": module, "spans": spans}


def _calc_pack(tmp_path: Path, name: str, fmt: str, version: str) -> tuple[Path, dict]:
    root = Path(shutil.copytree(FIXTURE, tmp_path / name))
    decls = [
        {"asOf": "2026-11-10", "known": "2026-11-10"},
        {
            "extend": "Alpha",
            "derived": [
                {
                    "derived": "doubled",
                    "type": "Int",
                    "unit": "count",
                    "value": {"arith": ["*", {"path": ["size"]}, {"lit": "2"}]},
                }
            ],
        },
    ]
    module = {"rezono": version, "pack": "minimal", "use": [], "decls": decls}
    form = _form(fmt, module)
    rezono_dir = root / "rezono"
    rezono_dir.mkdir(exist_ok=True)
    (rezono_dir / "scoring.rezono").write_text(f"rezono {version}\npack minimal\n", encoding="utf-8", newline="\n")
    (rezono_dir / "scoring.json").write_text(json.dumps(form, sort_keys=True), encoding="utf-8")
    meta_path = root / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["rezono"] = [{"module": "rezono/scoring.rezono", "form": "rezono/scoring.json", "layer": "conclusions"}]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return root, form


def test_rezono_module_5_calculation_lowers_to_calc_ir(tmp_path):
    # rezono 0 keeps lowering calculations to rezono.calc/1 (decisions/language-rezono-1.md section 5.6);
    # rezono 1 derivations with unit/as-of lower to rezono.rules/2 (test_rezono_1_derived_retires_calc_fallback).
    v0_dir, v0_form = _calc_pack(tmp_path, "calc_v0", rezono_module.IDENTIFIER_FORMAT, "0")
    assert rezono_calc.has_calculation(v0_form) is True
    v0_files = emit.compile_pack(pack.read(v0_dir))
    assert "ir/calc.json" in v0_files

    # Counter-case: a rezono.module/5 schema-only module carries no calculation and records language_version "1".
    schema_only = _form(
        rezono_module.REZONO_1_FORMAT,
        {"rezono": "1", "pack": "minimal", "use": [], "decls": [{"kind": "Note", "world": "closed", "slots": [], "derived": []}]},
    )
    assert rezono_calc.has_calculation(schema_only) is False
    schema_dir = Path(shutil.copytree(FIXTURE, tmp_path / "schema_v1"))
    rezono_dir = schema_dir / "rezono"
    rezono_dir.mkdir(exist_ok=True)
    (rezono_dir / "note.rezono").write_text("rezono 1\npack minimal\n", encoding="utf-8", newline="\n")
    (rezono_dir / "note.json").write_text(json.dumps(schema_only, sort_keys=True), encoding="utf-8")
    meta_path = schema_dir / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["rezono"] = [{"module": "rezono/note.rezono", "form": "rezono/note.json", "layer": "facts"}]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    schema_files = emit.compile_pack(pack.read(schema_dir))
    assert "ir/calc.json" not in schema_files
    assert json.loads(schema_files["bundle/schema-bundle.json"])["pack"]["language_version"] == "1"


def _dataset_form(fmt: str, version: str | None, *, spans: list[dict] | None = None) -> dict:
    module: dict = {
        "pack": "minimal",
        "use": [],
        "decls": [
            {
                "dataset": "sample",
                "decls": [
                    {
                        "source": "notices",
                        "fields": {"kind": "tool", "name": "Notice reader", "position": "L1"},
                    },
                    {
                        "fact": "Alpha",
                        "source": "notices",
                        "columns": ["id", "title", "size"],
                        "sourceColumns": ["revision"],
                        "rows": [
                            [{"lit": "a-one"}, {"lit": '"One"'}, {"lit": "4"}, {"lit": '"1.2.0"'}],
                            [{"lit": "a-two"}, {"lit": '"Two"'}, {"boundary": "omitted"}, {"boundary": "omitted"}],
                        ],
                    },
                ],
            }
        ],
    }
    if version is not None:
        module["rezono"] = version
    return {"format": fmt, "module": module, "spans": [] if spans is None else spans}


def test_rezono_module_5_dataset_loads_and_publishes_sources(tmp_path, capsys):
    root = Path(shutil.copytree(FIXTURE, tmp_path / "dataset_v5"))
    data_dir = root / "rezono" / "data"
    data_dir.mkdir(parents=True)
    v5_form = _dataset_form(rezono_module.REZONO_1_FORMAT, "1")
    form_path = data_dir / "sample.json"
    form_path.write_text(json.dumps(v5_form, sort_keys=True), encoding="utf-8")
    (data_dir / "sample.rezono").write_text("rezono 1\npack minimal\ndataset sample\n", encoding="utf-8", newline="\n")
    meta_path = root / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["rezono"] = [{"module": "rezono/data/sample.rezono", "form": "rezono/data/sample.json", "layer": "facts"}]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")

    model = pack.read(root)
    assert facts.files(root) == [form_path]
    assert len(facts.named_dataset_decls(v5_form)) == 2
    assert facts.untyped_dataset(v5_form) == {
        "alpha": [
            {"id": "a-one", "title": "One", "size": 4},
            {"id": "a-two", "title": "Two"},
        ]
    }
    assert facts.document(form_path) == facts.untyped_dataset(v5_form)
    assert facts.document(form_path, model) == facts.untyped_dataset(v5_form)

    rows = facts.load(model, form_path)
    assert rows["alpha"] == [("a-one",), ("a-two",)]
    assert rows["alpha__title"] == [("a-one", "One"), ("a-two", "Two")]
    assert rows["alpha__size"] == [("a-one", 4)]

    cited = sources.cited(v5_form, "sample.json")
    assert cited[("alpha", 0)] == {"kind": "tool", "name": "Notice reader", "position": "L1", "revision": "1.2.0"}
    assert cited[("alpha", 1)] == {"kind": "tool", "name": "Notice reader", "position": "L1"}

    output = tmp_path / "compiled"
    assert main(["compile", str(root), str(output)]) == 0, capsys.readouterr().err
    published = {
        (entry["row"]["relation"], entry["row"]["key"]): entry["sources"]
        for entry in json.loads((output / "generated/sources.json").read_bytes())
    }
    assert published[("alpha", '["a-one"]')] == [
        {"kind": "tool", "name": "Notice reader", "position": "L1", "revision": "1.2.0"}
    ]
    assert published[("alpha", '["a-two"]')] == [
        {"kind": "tool", "name": "Notice reader", "position": "L1"}
    ]

    # Version consistency counter-cases must still be enforced.
    judged = facts.schema(model)
    with pytest.raises(facts.LoadError, match="R027"):
        facts.located_scalar_dataset(judged, _dataset_form(rezono_module.REZONO_1_FORMAT, "0"))
    with pytest.raises(facts.LoadError, match="R028"):
        facts.located_scalar_dataset(judged, _dataset_form(rezono_module.REZONO_1_FORMAT, None))
    with pytest.raises(facts.LoadError, match="says 0, not 1"):
        facts.located_scalar_dataset(judged, _dataset_form(rezono_module.DATASET_FORMAT, "1"))


def test_rezono_module_5_authored_dataset_and_fact_tables(tmp_path, monkeypatch):
    # 1. Authored rezono.module/5 module with a trailing dataset (kind + dataset).
    trailing_dir = Path(shutil.copytree(FIXTURE, tmp_path / "trailing_v5"))
    rezono_dir = trailing_dir / "rezono"
    rezono_dir.mkdir()
    trailing_module = {
        "rezono": "1",
        "pack": "minimal",
        "use": [],
        "decls": [
            {
                "kind": "Gauge",
                "world": "closed",
                "slots": [{"slot": "reading", "type": "Int"}],
                "derived": [],
            },
            {
                "dataset": "gauges",
                "decls": [
                    {
                        "fact": "Gauge",
                        "columns": ["id", "reading"],
                        "rows": [[{"lit": "g1"}, {"lit": "12"}]],
                    }
                ],
            },
        ],
    }
    trailing_form = _form(rezono_module.REZONO_1_FORMAT, trailing_module, line="7", start="10", end="15")
    (rezono_dir / "gauges.json").write_text(json.dumps(trailing_form, sort_keys=True), encoding="utf-8")
    (rezono_dir / "gauges.rezono").write_text(
        "rezono 1\npack minimal\nkind Gauge world closed\n  reading: Int\ndataset gauges\n  fact Gauge\n    | id | reading |\n    | g1 | 12 |\n",
        encoding="utf-8",
        newline="\n",
    )
    meta_path = trailing_dir / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["rezono"] = [{"module": "rezono/gauges.rezono", "form": "rezono/gauges.json", "layer": "facts"}]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")

    monkeypatch.setattr(rezono_module, "warm_pack_modules", lambda *args, **kwargs: None)
    monkeypatch.setattr(rezono_module, "warm_packs", lambda *args, **kwargs: None)
    monkeypatch.setattr(rezono_module, "authored_form", lambda *args, **kwargs: trailing_form)

    trailing_pack = pack.read(trailing_dir)
    assert trailing_pack.language_version == "1"
    assert "gauge" in trailing_pack.kinds
    assert facts.files(trailing_dir) == [rezono_dir / "gauges.json"]
    assert facts.load(trailing_pack, rezono_dir / "gauges.json")["gauge__reading"] == [("g1", 12)]
    trailing_sources = {
        (entry["row"]["relation"], entry["row"]["key"]): entry["sources"]
        for entry in sources.read(trailing_pack, trailing_dir)
    }
    assert trailing_sources[("gauge__reading", '["g1","12"]')] == [
        {"kind": "pack", "name": "rezono/gauges.rezono", "position": "7"}
    ]

    # 2. Authored rezono.module/5 fact-tables-only module (no dataset wrapper).
    tables_dir = Path(shutil.copytree(FIXTURE, tmp_path / "tables_v5"))
    tables_rezono = tables_dir / "rezono"
    tables_rezono.mkdir()
    tables_module = {
        "rezono": "1",
        "pack": "minimal",
        "use": [],
        "decls": [
            {
                "fact": "Alpha",
                "columns": ["id", "title", "size"],
                "rows": [[{"lit": "t1"}, {"lit": '"Table row"'}, {"lit": "5"}]],
            }
        ],
    }
    tables_form = _form(rezono_module.REZONO_1_FORMAT, tables_module, line="5", start="10", end="15")
    (tables_rezono / "items.json").write_text(json.dumps(tables_form, sort_keys=True), encoding="utf-8")
    (tables_rezono / "items.rezono").write_text(
        'rezono 1\npack minimal\nfact Alpha\n  | id | title | size |\n  | t1 | "Table row" | 5 |\n',
        encoding="utf-8",
        newline="\n",
    )
    t_meta_path = tables_dir / "pack.yaml"
    t_meta = yaml.safe_load(t_meta_path.read_text(encoding="utf-8"))
    t_meta["rezono"] = [{"module": "rezono/items.rezono", "form": "rezono/items.json", "layer": "facts"}]
    t_meta_path.write_text(yaml.safe_dump(t_meta, sort_keys=False), encoding="utf-8", newline="\n")

    monkeypatch.setattr(rezono_module, "authored_form", lambda *args, **kwargs: tables_form)

    assert rezono_module.is_dataset_form(tables_rezono / "items.json", tables_rezono / "items.rezono") is True
    tables_pack = pack.read(tables_dir)
    assert facts.files(tables_dir) == [tables_rezono / "items.json"]
    assert facts.load(tables_pack, tables_rezono / "items.json")["alpha__size"] == [("t1", 5)]
    table_sources = {
        (entry["row"]["relation"], entry["row"]["key"]): entry["sources"]
        for entry in sources.read(tables_pack, tables_dir)
    }
    assert table_sources[("alpha__size", '["t1","5"]')] == [
        {"kind": "pack", "name": "rezono/items.rezono", "position": "5"}
    ]
