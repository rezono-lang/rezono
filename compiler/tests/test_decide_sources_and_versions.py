"""Regression tests for `decide` source validation, inlined origin propagation, and dated version resolution."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import facts, pack, rezono_module, sources
from support import FIXTURE

TOOL = {"kind": "tool", "name": "Register scan", "position": "run 1"}
GIT_SRC = {
    "kind": "git",
    "name": "example/notes",
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "position": "docs/notes.md#L1",
}


def _dataset_form(decls: list[dict], *, version: str = "0") -> dict:
    fmt = rezono_module.REZONO_1_FORMAT if version == "1" else rezono_module.DATASET_FORMAT
    return {
        "format": fmt,
        "spans": [],
        "module": {
            "rezono": version,
            "pack": "minimal",
            "use": [],
            "decls": [{"dataset": "sample", "decls": decls}],
        },
    }


def _make_pack(
    tmp_path: Path,
    name: str,
    decls: list[dict],
    *,
    version: str = "0",
    extra_schema: dict | None = None,
) -> tuple[pack.Pack, Path, Path]:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    if extra_schema is not None:
        schema_path = directory / "schema" / "minimal.yaml"
        schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        for key, value in extra_schema.items():
            schema_doc.setdefault(key, {}).update(value)
        schema_path.write_text(yaml.safe_dump(schema_doc, sort_keys=False), encoding="utf-8", newline="\n")
    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    (folder / "sample.rezono").write_text(
        f"rezono {version}\npack minimal\ndataset sample\n",
        encoding="utf-8",
        newline="\n",
    )
    form_path = folder / "sample.json"
    form_path.write_text(json.dumps(_dataset_form(decls, version=version), sort_keys=True), encoding="utf-8", newline="\n")
    meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
    meta.setdefault("rezono", []).append(
        {"module": "rezono/sample.rezono", "form": "rezono/sample.json", "layer": "facts"},
    )
    (directory / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
    return pack.read(directory), directory, form_path


def _base_alpha_table(*, source: str | None = None, columns: list[str] | None = None, rows: list | None = None) -> dict:
    table: dict = {
        "fact": "Alpha",
        "columns": columns or ["id", "title"],
        "rows": rows if rows is not None else [[{"lit": "a-one"}, {"lit": '"One"'}]],
    }
    if source is not None:
        table["source"] = source
    return table


def test_decide_unknown_or_malformed_source_citation_raises_load_error(tmp_path):
    bad_cases = [
        ("undeclared", "nonexistent_source", "unknown_source"),
        ("undeclared_with_fragment", "nonexistent_source#L12", "unknown_source"),
        ("empty_fragment", "notes#", "invalid_source"),
        ("whitespace_fragment", "notes#   ", "invalid_source"),
    ]
    for case_name, ref, expected_code in bad_cases:
        decls = [
            {"source": "notes", "fields": GIT_SRC},
            _base_alpha_table(),
            {
                "decide": "Set size",
                "by": "reviewer",
                "on": "2026-11-20",
                "source": ref,
                "set": [{"path": ["a-one", "size"], "value": {"lit": "3"}}],
            },
        ]
        model, directory, _ = _make_pack(tmp_path, case_name, decls)
        with pytest.raises(facts.LoadError) as caught:
            sources.read(model, directory)
        assert [d.code for d in caught.value.diagnostics] == [expected_code], (case_name, caught.value.diagnostics)

    # Even when the decide block sets only n/a (so no decided cell row is emitted), an unknown @ source fails.
    na_decls = [
        _base_alpha_table(),
        {
            "decide": "Leave size absent",
            "by": "reviewer",
            "on": "2026-11-20",
            "source": "nonexistent_source",
            "set": [{"path": ["a-one", "size"], "value": {"lit": "n/a"}}],
        },
    ]
    na_model, na_dir, _ = _make_pack(tmp_path, "undeclared_na", na_decls)
    with pytest.raises(facts.LoadError) as caught:
        sources.read(na_model, na_dir)
    assert [d.code for d in caught.value.diagnostics] == ["unknown_source"]

    # Counter-case: valid declared source and valid source#fragment attach both person and cited sources.
    for case_name, ref, expected_pos in (
        ("valid_plain", "notes", "docs/notes.md#L1"),
        ("valid_fragment", "notes#L42", "docs/notes.md#L42"),
    ):
        decls = [
            {"source": "notes", "fields": GIT_SRC},
            _base_alpha_table(),
            {
                "decide": "Set size",
                "by": "reviewer",
                "on": "2026-11-20",
                "source": ref,
                "set": [{"path": ["a-one", "size"], "value": {"lit": "3"}}],
            },
        ]
        model, directory, _ = _make_pack(tmp_path, case_name, decls)
        entries = sources.read(model, directory)
        size_entries = [e for e in entries if e["row"]["relation"] == "alpha__size"]
        assert len(size_entries) == 1
        kinds = {s["kind"] for s in size_entries[0]["sources"]}
        assert kinds == {"person", "git"}
        git_sources = [s for s in size_entries[0]["sources"] if s["kind"] == "git"]
        assert git_sources == [GIT_SRC | {"position": expected_pos}]


def test_decide_inlined_slot_propagates_origin_to_child_rows(tmp_path):
    inlined_schema = {
        "classes": {
            "Tag": {
                "attributes": {
                    "label": {"required": True},
                },
            },
            "Detail": {
                "attributes": {
                    "note": {"required": True},
                    "tag": {"range": "Tag", "inlined": True},
                },
            },
            "Entry": {
                "attributes": {
                    "note": {"required": True},
                },
            },
            "Alpha": {
                "attributes": {
                    "id": {"identifier": True},
                    "title": {"required": True},
                    "size": {"range": "Count", "minimum_value": 0, "maximum_value": 9},
                    "fallback_detail": {"range": "Detail", "inlined": True},
                    "detail": {"range": "Detail", "inlined": True},
                    "entries": {"range": "Entry", "inlined": True, "multivalued": True},
                },
            },
        },
    }
    decls = [
        {"source": "notes", "fields": TOOL},
        _base_alpha_table(
            columns=["id", "title", "fallback_detail"],
            rows=[[
                {"lit": "a-one"},
                {"lit": '"One"'},
                {"record": {"note": {"lit": '"from-table"'}}},
            ]],
        ),
        {
            "decide": "Set inlined detail and entries",
            "by": "reviewer",
            "on": "2026-11-20",
            "source": "notes",
            "set": [
                {
                    "path": ["a-one", "detail"],
                    "value": {"record": {
                        "note": {"lit": '"from-decide"'},
                        "tag": {"record": {"label": {"lit": '"nested-tag"'}}},
                    }},
                },
                {
                    "path": ["a-one", "entries"],
                    "value": {"list": [
                        {"record": {"note": {"lit": '"e1"'}}},
                        {"record": {"note": {"lit": '"e2"'}}},
                    ]},
                },
            ],
        },
    ]
    model, directory, _ = _make_pack(tmp_path, "inlined_uncited_parent", decls, extra_schema=inlined_schema)
    entries = sources.read(model, directory)
    by_rel_key = {(e["row"]["relation"], e["row"]["key"]): e["sources"] for e in entries}

    decided_rows = [
        ("alpha__detail", '["a-one","a-one/alpha.detail"]'),
        ("detail", '["a-one/alpha.detail"]'),
        ("detail__note", '["a-one/alpha.detail","from-decide"]'),
        ("detail__tag", '["a-one/alpha.detail","a-one%2Falpha.detail/detail.tag"]'),
        ("tag", '["a-one%2Falpha.detail/detail.tag"]'),
        ("tag__label", '["a-one%2Falpha.detail/detail.tag","nested-tag"]'),
        ("alpha__entries", '["a-one","a-one/alpha.entries/1"]'),
        ("alpha__entries", '["a-one","a-one/alpha.entries/2"]'),
        ("entry", '["a-one/alpha.entries/1"]'),
        ("entry", '["a-one/alpha.entries/2"]'),
        ("entry__note", '["a-one/alpha.entries/1","e1"]'),
        ("entry__note", '["a-one/alpha.entries/2","e2"]'),
    ]
    for row_key in decided_rows:
        assert row_key in by_rel_key, f"missing expected row {row_key} in {sorted(by_rel_key)}"
        src_kinds = {s["kind"] for s in by_rel_key[row_key]}
        assert src_kinds == {"person", "tool"}, (row_key, by_rel_key[row_key])

    # Counter-case: the non-decided inlined slot from the uncited fact table keeps only its implicit `pack` source.
    for row_key in (
        ("alpha", '["a-one"]'),
        ("alpha__fallback_detail", '["a-one","a-one/alpha.fallback_detail"]'),
        ("detail", '["a-one/alpha.fallback_detail"]'),
        ("detail__note", '["a-one/alpha.fallback_detail","from-table"]'),
    ):
        assert {s["kind"] for s in by_rel_key[row_key]} == {"pack"}, (row_key, by_rel_key[row_key])

    # Missing origins must only report the uncited parent and its non-decided inlined fallback, never the decided children.
    missing = sources.missing_origins(model, entries, directory)
    missing_ids = {(m.kind, m.identifier) for m in missing}
    assert missing_ids == {("alpha", "a-one"), ("detail", "a-one/alpha.fallback_detail")}

    # On rezono 1 with a cited fact table, every parent and decided inlined child row has an origin.
    cited_decls = [
        {"source": "notes", "fields": TOOL},
        _base_alpha_table(source="notes"),
        decls[2],
    ]
    v1_model, v1_dir, _ = _make_pack(tmp_path, "inlined_v1_cited", cited_decls, version="1", extra_schema=inlined_schema)
    v1_entries = sources.read(v1_model, v1_dir)
    assert sources.missing_origins(v1_model, v1_entries, v1_dir) == []


def test_dated_fact_row_and_dated_decide_resolve_jointly_by_known_date(tmp_path):
    decls = [
        _base_alpha_table(),
        {
            "fact": "alpha",
            "id": "a-one",
            "valid": ["2026-01-01", "2027-01-01"],
            "known": "2025-12-01",
            "set": [{"slot": "size", "value": {"lit": "3"}}],
        },
        {
            "decide": "Revise size for spring",
            "by": "reviewer",
            "on": "2026-03-01",
            "valid": ["2026-03-01", "2027-01-01"],
            "known": "2026-03-01",
            "set": [{"path": ["a-one", "size"], "value": {"lit": "5"}}],
        },
    ]
    model, _, form_path = _make_pack(tmp_path, "joint_dated", decls)

    # Later as_of and known: both apply, decide wins by newer known date.
    later = facts.load(model, form_path, as_of="2026-04-01", known="2026-04-01")
    assert later["alpha__size"] == [("a-one", 5)]

    # Earlier as_of (outside decide's valid window): fact row applies and wins cleanly.
    earlier_as_of = facts.load(model, form_path, as_of="2026-02-01", known="2026-04-01")
    assert earlier_as_of["alpha__size"] == [("a-one", 3)]

    # Earlier known (before decide's known date): fact row applies and wins cleanly.
    earlier_known = facts.load(model, form_path, as_of="2026-04-01", known="2026-02-01")
    assert earlier_known["alpha__size"] == [("a-one", 3)]

    # Outside both valid windows: slot table is empty.
    before_any = facts.load(model, form_path, as_of="2025-06-01", known="2026-04-01")
    assert before_any["alpha__size"] == []

    # decided_cells attributes the cell to the decide block only when the decide block won.
    raw_form = json.loads(form_path.read_text(encoding="utf-8"))
    judged = facts.schema(model)
    import datetime as dt

    _, _, later_decided = facts.located_scalar_dataset_with_decides(
        judged, raw_form, as_of=dt.date(2026, 4, 1), known=dt.date(2026, 4, 1),
    )
    assert later_decided == {("alpha", 0, "size"): (2, 0)}

    _, _, earlier_decided = facts.located_scalar_dataset_with_decides(
        judged, raw_form, as_of=dt.date(2026, 2, 1), known=dt.date(2026, 4, 1),
    )
    assert earlier_decided == {}

    # untyped_dataset also resolves dated fact row + dated decide jointly.
    untyped_later = facts.untyped_dataset(raw_form, as_of=dt.date(2026, 4, 1), known=dt.date(2026, 4, 1))
    assert untyped_later["alpha"][0]["size"] == 5
    untyped_earlier = facts.untyped_dataset(raw_form, as_of=dt.date(2026, 2, 1), known=dt.date(2026, 4, 1))
    assert untyped_earlier["alpha"][0]["size"] == 3

    # Counter-case: dated fact row and dated decide with the same known date on overlapping windows raise versions_overlap.
    tie_decls = [
        _base_alpha_table(),
        {
            "fact": "alpha",
            "id": "a-one",
            "valid": ["2026-01-01", "2027-01-01"],
            "known": "2026-03-01",
            "set": [{"slot": "size", "value": {"lit": "3"}}],
        },
        {
            "decide": "Conflicting size",
            "by": "reviewer",
            "on": "2026-03-01",
            "valid": ["2026-03-01", "2027-01-01"],
            "known": "2026-03-01",
            "set": [{"path": ["a-one", "size"], "value": {"lit": "5"}}],
        },
    ]
    tie_model, _, tie_path = _make_pack(tmp_path, "joint_tie", tie_decls)
    with pytest.raises(facts.LoadError, match="versions_overlap") as caught:
        facts.load(tie_model, tie_path, as_of="2026-04-01", known="2026-04-01")
    assert [d.code for d in caught.value.diagnostics] == ["versions_overlap"]
    # Outside the decide window, the same-known fact row still resolves cleanly.
    assert facts.load(tie_model, tie_path, as_of="2026-02-01", known="2026-04-01")["alpha__size"] == [("a-one", 3)]


def test_undated_fact_row_and_dated_decide_still_raises_versions_overlap(tmp_path):
    # Undated fact row + dated decide on the same slot must fail with versions_overlap (inside and outside window).
    undated_fact_plus_dated_decide = [
        _base_alpha_table(),
        {"fact": "alpha", "id": "a-one", "set": [{"slot": "size", "value": {"lit": "1"}}]},
        {
            "decide": "Dated override",
            "by": "reviewer",
            "on": "2026-03-01",
            "valid": ["2026-03-01", "2027-01-01"],
            "known": "2026-03-01",
            "set": [{"path": ["a-one", "size"], "value": {"lit": "5"}}],
        },
    ]
    model1, _, path1 = _make_pack(tmp_path, "undated_fact_dated_decide", undated_fact_plus_dated_decide)
    for as_of in ("2026-04-01", "2025-06-01"):
        with pytest.raises(facts.LoadError, match="versions_overlap") as caught:
            facts.load(model1, path1, as_of=as_of, known="2026-04-01")
        assert [d.code for d in caught.value.diagnostics] == ["versions_overlap"]

    # Undated decide + dated fact row on the same slot must also fail with versions_overlap.
    undated_decide_plus_dated_fact = [
        _base_alpha_table(),
        {
            "decide": "Undated size",
            "by": "reviewer",
            "on": "2026-01-01",
            "set": [{"path": ["a-one", "size"], "value": {"lit": "1"}}],
        },
        {
            "fact": "alpha",
            "id": "a-one",
            "valid": ["2026-03-01", "2027-01-01"],
            "known": "2026-03-01",
            "set": [{"slot": "size", "value": {"lit": "5"}}],
        },
    ]
    model2, _, path2 = _make_pack(tmp_path, "undated_decide_dated_fact", undated_decide_plus_dated_fact)
    for as_of in ("2026-04-01", "2025-06-01"):
        with pytest.raises(facts.LoadError, match="versions_overlap") as caught:
            facts.load(model2, path2, as_of=as_of, known="2026-04-01")
        assert [d.code for d in caught.value.diagnostics] == ["versions_overlap"]

    # Undated fact table column + dated decide on the same slot must also fail with versions_overlap.
    table_plus_dated_decide = [
        _base_alpha_table(columns=["id", "title", "size"], rows=[[{"lit": "a-one"}, {"lit": '"One"'}, {"lit": "1"}]]),
        {
            "decide": "Dated override",
            "by": "reviewer",
            "on": "2026-03-01",
            "valid": ["2026-03-01", "2027-01-01"],
            "known": "2026-03-01",
            "set": [{"path": ["a-one", "size"], "value": {"lit": "5"}}],
        },
    ]
    model3, _, path3 = _make_pack(tmp_path, "table_dated_decide", table_plus_dated_decide)
    with pytest.raises(facts.LoadError, match="versions_overlap") as caught:
        facts.load(model3, path3, as_of="2026-04-01", known="2026-04-01")
    assert [d.code for d in caught.value.diagnostics] == ["versions_overlap"]
