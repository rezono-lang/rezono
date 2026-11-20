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
