"""Dated fact rows lower to versioned slot values selected on (as_of, known)
(decisions/language-dated-facts.md, docs/rezono/v0.md section 5a).

The module form is written by hand from decisions/language-dated-facts.md so this test isolates lowering
from the reader (rezono/test/test_dated_fact.py). The expected slot rows per (as_of, known) pair are
computed by hand from section 5a.
"""

from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import facts, pack
from support import FIXTURE


class MissingDatedFactLowering(AssertionError):
    """facts.load did not select dated fact rows on (as_of, known) as decisions/language-dated-facts.md says."""


def dataset_form(extra_rows: list[dict]) -> dict:
    return {
        "format": "rezono.module/2",
        "spans": [],
        "module": {
            "rezono": "0",
            "pack": "minimal",
            "use": [],
            "decls": [{
                "dataset": "dated",
                "decls": [
                    {
                        "fact": "Alpha",
                        "columns": ["id", "title"],
                        "rows": [
                            [{"lit": "a-one"}, {"lit": '"One"'}],
                            [{"lit": "a-two"}, {"lit": '"Two"'}],
                        ],
                    },
                    *extra_rows,
                ],
            }],
        },
    }


def make_pack(tmp_path: Path, name: str, rows: list[dict]) -> tuple[pack.Pack, Path]:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    (directory / "rezono").mkdir()
    (directory / "rezono/dated.rezono").write_text("rezono 0\npack minimal\ndataset dated\n", encoding="utf-8")
    form_path = directory / "rezono/dated.json"
    form_path.write_text(json.dumps(dataset_form(rows)), encoding="utf-8")
    with (directory / "pack.yaml").open("a", encoding="utf-8") as stream:
        yaml.safe_dump({"rezono": [{"module": "rezono/dated.rezono", "form": "rezono/dated.json", "layer": "facts"}]},
                       stream)
    return pack.read(directory), form_path


DATED_ROWS = [
    {"fact": "alpha", "id": "a-one", "valid": ["2026-01-01", "2027-01-01"], "known": "2025-12-01",
     "set": [{"slot": "size", "value": {"lit": "3"}}]},
    {"fact": "alpha", "id": "a-one", "valid": ["2026-01-01", "2027-01-01"], "known": "2026-03-01",
     "set": [{"slot": "size", "value": {"lit": "5"}}]},
    {"fact": "alpha", "id": "a-one", "valid": ["2027-01-01"], "known": "2026-12-01",
     "set": [{"slot": "size", "value": {"lit": "8"}}]},
]


def test_lower_dated_fact(tmp_path):
    model, form_path = make_pack(tmp_path, "valid", DATED_ROWS)
    try:
        early = facts.load(model, form_path, as_of="2026-02-01", known="2026-02-15")
        corrected = facts.load(model, form_path, as_of="2026-02-01", known="2026-04-01")
        open_end = facts.load(model, form_path, as_of="2027-01-15", known="2027-01-20")
        before_any = facts.load(model, form_path, as_of="2025-06-01", known="2026-06-01")
    except (TypeError, facts.LoadError) as error:
        raise MissingDatedFactLowering(str(error)) from error

    # Hand-computed expectations from docs/rezono/v0.md section 5a:
    # a-two has no dated size version, so only a-one appears in alpha__size when a version applies.
    assert early["alpha"] == [("a-one",), ("a-two",)]
    assert early["alpha__size"] == [("a-one", 3)]
    assert corrected["alpha__size"] == [("a-one", 5)]
    assert open_end["alpha__size"] == [("a-one", 8)]
    assert before_any["alpha__size"] == []

    # Counter-case 1: two overlapping dated rows with the same known date fail with versions_overlap.
    overlap_rows = [
        {"fact": "alpha", "id": "a-one", "valid": ["2026-01-01", "2027-01-01"], "known": "2026-01-01",
         "set": [{"slot": "size", "value": {"lit": "3"}}]},
        {"fact": "alpha", "id": "a-one", "valid": ["2026-06-01", "2027-01-01"], "known": "2026-01-01",
         "set": [{"slot": "size", "value": {"lit": "9"}}]},
    ]
    overlap_model, overlap_path = make_pack(tmp_path, "overlap", overlap_rows)
    with pytest.raises(facts.LoadError, match="versions_overlap"):
        facts.load(overlap_model, overlap_path, as_of="2026-07-01", known="2026-08-01")

    # Counter-case 2: a dated row never creates a record that no fact table creates.
    orphan_rows = [
        {"fact": "alpha", "id": "ghost", "valid": ["2026-01-01"], "known": "2026-01-01",
         "set": [{"slot": "size", "value": {"lit": "4"}}]},
    ]
    orphan_model, orphan_path = make_pack(tmp_path, "orphan", orphan_rows)
    with pytest.raises(facts.LoadError):
        facts.load(orphan_model, orphan_path, as_of="2026-07-01", known="2026-08-01")


@pytest.mark.parametrize("bounds", [
    ["2026-01-01", "2026-01-01"],
    ["2027-01-01", "2026-01-01"],
])
def test_dated_fact_rejects_empty_and_reversed_valid_ranges(tmp_path, bounds):
    rows = [
        {"fact": "alpha", "id": "a-one", "valid": bounds, "known": "2025-12-01",
         "set": [{"slot": "size", "value": {"lit": "3"}}]},
    ]
    model, form_path = make_pack(tmp_path, f"bad-range-{bounds[0]}-{bounds[1]}", rows)
    with pytest.raises(facts.LoadError) as caught:
        facts.load(model, form_path, as_of="2026-06-01", known="2026-06-01")
    assert [d.code for d in caught.value.diagnostics] == ["invalid_date_range"]


def test_dated_fact_rejects_mixing_undated_and_dated_slot(tmp_path):
    # Undated row + dated row with explicit known must fail consistently with versions_overlap,
    # both when the dated row applies and when as_of falls outside its valid range.
    with_known = [
        {"fact": "alpha", "id": "a-one", "set": [{"slot": "size", "value": {"lit": "1"}}]},
        {"fact": "alpha", "id": "a-one", "valid": ["2026-01-01", "2027-01-01"], "known": "2025-12-01",
         "set": [{"slot": "size", "value": {"lit": "3"}}]},
    ]
    model, form_path = make_pack(tmp_path, "mix-with-known", with_known)
    for as_of in ("2026-02-01", "2025-06-01"):
        with pytest.raises(facts.LoadError, match="versions_overlap") as caught:
            facts.load(model, form_path, as_of=as_of, known="2026-02-15")
        assert [d.code for d in caught.value.diagnostics] == ["versions_overlap"]

    # Undated row + dated row without known also fails with versions_overlap.
    without_known = [
        {"fact": "alpha", "id": "a-one", "set": [{"slot": "size", "value": {"lit": "1"}}]},
        {"fact": "alpha", "id": "a-one", "valid": ["2026-01-01", "2027-01-01"],
         "set": [{"slot": "size", "value": {"lit": "3"}}]},
    ]
    model2, form_path2 = make_pack(tmp_path, "mix-without-known", without_known)
    with pytest.raises(facts.LoadError, match="versions_overlap") as caught:
        facts.load(model2, form_path2, as_of="2026-02-01", known="2026-02-15")
    assert [d.code for d in caught.value.diagnostics] == ["versions_overlap"]

    # Separate records may still use undated and dated values for the same slot.
    separate_records = [
        {"fact": "alpha", "id": "a-two", "set": [{"slot": "size", "value": {"lit": "2"}}]},
        {"fact": "alpha", "id": "a-one", "valid": ["2026-01-01", "2027-01-01"], "known": "2025-12-01",
         "set": [{"slot": "size", "value": {"lit": "3"}}]},
    ]
    model3, form_path3 = make_pack(tmp_path, "separate-records", separate_records)
    loaded = facts.load(model3, form_path3, as_of="2026-02-01", known="2026-02-15")
    assert loaded["alpha__size"] == [("a-one", 3), ("a-two", 2)]
