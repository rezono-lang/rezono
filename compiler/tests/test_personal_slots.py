"""Personal slots and compiler refusal `R054` (decisions/personal-data-handling.md).

A slot marked `personal` may not be read by any rule (positive literal, negative literal, or aggregate).
The compiler refuses any rule reading a personal slot with diagnostic `R054`, while a pack whose rules read
only non-personal slots compiles cleanly and marks `personal: true` on the attribute in `schema-bundle.json`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import emit, pack, rules_dl

ROOT = Path(__file__).resolve().parents[2]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"


def _personal_pack(directory: Path, rule_text: str) -> Path:
    shutil.copytree(MINIMAL, directory)
    schema_path = directory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema["classes"]["Alpha"]["attributes"]["secret_note"] = {
        "range": "string",
        "annotations": {"personal": True},
    }
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")

    labels_path = directory / "labels" / "nl.yaml"
    labels_path.write_text(
        labels_path.read_text(encoding="utf-8") + "alpha.secret_note: vertrouwelijke aantekening\n",
        encoding="utf-8",
        newline="\n",
    )

    (directory / "rules").mkdir()
    (directory / "rules" / "derive.dl").write_text(rule_text, encoding="utf-8", newline="\n")
    return directory


def test_rule_reading_personal_slot_is_refused(tmp_path: Path):
    # 1. Positive body literal reading a personal slot must be refused with R054.
    positive_dir = _personal_pack(
        tmp_path / "positive",
        ".decl exposed(x: symbol, v: symbol)\n"
        "exposed(x, v) :- alpha__secret_note(x, v).\n",
    )
    try:
        emit.compile_pack(pack.read(positive_dir))
    except (pack.CompileError, rules_dl.RuleError) as pos_err:
        pos_codes = [d.code for d in getattr(pos_err, "diagnostics", ())]
        assert "R054" in pos_codes or "R054" in str(pos_err), (
            f"expected R054 diagnostic when a rule reads personal slot alpha.secret_note, got: {pos_err}"
        )
        assert "secret_note" in str(pos_err), pos_err
    else:
        raise AssertionError("rule reading personal slot alpha__secret_note must be refused with R054")

    # 2. Aggregate reading a personal slot must also be refused with R054.
    agg_dir = _personal_pack(
        tmp_path / "aggregate",
        ".decl counted(x: symbol, n: number)\n"
        "counted(x, n) :- alpha(x), n = count : { alpha__secret_note(x, _) }.\n",
    )
    try:
        emit.compile_pack(pack.read(agg_dir))
    except (pack.CompileError, rules_dl.RuleError) as agg_err:
        agg_codes = [d.code for d in getattr(agg_err, "diagnostics", ())]
        assert "R054" in agg_codes or "R054" in str(agg_err), (
            f"expected R054 diagnostic when an aggregate reads personal slot alpha.secret_note, got: {agg_err}"
        )
        assert "secret_note" in str(agg_err), agg_err
    else:
        raise AssertionError("aggregate reading personal slot alpha__secret_note must be refused with R054")

    # 3. Counter-case: a rule reading only a non-personal slot compiles cleanly and marks personal: true in bundle.
    ok_dir = _personal_pack(
        tmp_path / "allowed",
        ".decl titled(x: symbol, v: symbol)\n"
        "titled(x, v) :- alpha__title(x, v).\n",
    )
    model = pack.read(ok_dir)
    assert getattr(model.kinds["alpha"].slots["secret_note"], "personal", False) is True
    assert getattr(model.kinds["alpha"].slots["title"], "personal", False) is False

    compiled = emit.compile_pack(model)
    bundle = json.loads(compiled["bundle/schema-bundle.json"])
    attrs = {a["id"]: a for a in bundle["attributes"]}
    assert attrs["alpha.secret_note"].get("personal") is True
    assert "personal" not in attrs["alpha.title"]
