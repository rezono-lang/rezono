"""An intermediate invariant lowers to one publication violation rule (invariant: true) in ir/rules.json and
one typed IntermediateInvariant entry on Pack.intermediate_invariants (decisions/language-safe-steps.md,
sections 3 and 4).

The module form is written by hand from decisions/language-safe-steps.md so this test isolates lowering from
the TypeScript module reader (rezono/test/test_invariant_intermediate.py).
"""

from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, pack, rezono_module
from support import FIXTURE


class MissingIntermediateInvariantLowering(AssertionError):
    """pack.read did not lower invariant intermediate within <coverage> as decisions/language-safe-steps.md says."""


def spans_for(body: dict) -> list[dict]:
    return [
        {"at": pointer, "line": str(index + 3), "start": "0", "end": "1"}
        for index, pointer in enumerate(rezono_module.place_pointers(body))
    ]


def make_pack(tmp_path: Path, name: str, decls: list[dict], *, form_format: str = "rezono.module/4") -> Path:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / name / "minimal"))
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nmissing_guard: missing guard\nalpha_coverage: alpha coverage\nwrong_coverage: wrong coverage\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.missing_guard = {{Guard is missing.}}\n")
    (directory / "rezono").mkdir()
    (directory / "rezono/safety.rezono").write_text("rezono 0\npack minimal\n", encoding="utf-8")
    body = {"rezono": "0", "pack": "minimal", "use": [], "decls": decls}
    form = {"format": form_format, "spans": spans_for(body), "module": body}
    (directory / "rezono/safety.json").write_text(json.dumps(form), encoding="utf-8")
    with (directory / "pack.yaml").open("a", encoding="utf-8") as stream:
        yaml.safe_dump({"rezono": [{"module": "rezono/safety.rezono", "form": "rezono/safety.json", "layer": "facts"}]},
                       stream)
    return directory


def make_plain_invariant_pack(tmp_path: Path) -> Path:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "bare" / "minimal"))
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nmissing_guard: missing guard\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.missing_guard = {{Guard is missing.}}\n")
    (directory / "rules").mkdir()
    (directory / "rules/guard.dl").write_text(
        "// @invariant\n.decl missing_guard(item: symbol)\nmissing_guard(item) :- alpha(item).\n",
        encoding="utf-8",
    )
    return directory


COVERAGE_RULE = {
    "rule": "alpha_coverage",
    "columns": [{"name": "item", "type": "Alpha"}, {"name": "scope", "type": "Text"}],
    "when": {"and": [
        {"call": ["alpha", [{"path": ["item"]}]]},
        {"call": ["alpha__title", [{"path": ["item"]}, {"path": ["scope"]}]]},
    ]},
}

VIOLATION_BODY = {"call": ["alpha", [{"path": ["item"]}]]}


def violation_rule(options: list[dict]) -> dict:
    return {
        "rule": "missing_guard",
        "columns": [{"name": "item", "type": "Alpha"}],
        "options": options,
        "when": VIOLATION_BODY,
    }


@pytest.mark.xfail(
    strict=True,
    raises=MissingIntermediateInvariantLowering,
    reason="extra: decisions/language-safe-steps.md: Admit rezono.module/4 in compiler/rezono_compiler/rezono_module.py "
           "and lower rule heads with {invariant: intermediate, within: {relation: NAME}} into one publication "
           "violation rule with invariant: true in ir/rules.json and an IntermediateInvariant(relation, "
           "coverage_relation, key_binding) entry in Pack.intermediate_invariants (empty tuple when unused). "
           "Require every violation column to match a coverage key column in name and resolved schema type, "
           "allowing extra coverage columns for scopes/readings; refuse missing or incompatible coverage with "
           "CompileError.",
)
def test_lower_intermediate_invariant(tmp_path):
    # Counter-case 1: a bare publication invariant lowers as before and leaves intermediate_invariants empty.
    bare_dir = make_plain_invariant_pack(tmp_path)
    bare_model = pack.read(bare_dir)
    if not hasattr(bare_model, "intermediate_invariants"):
        raise MissingIntermediateInvariantLowering("Pack has no intermediate_invariants field")
    assert bare_model.intermediate_invariants == ()

    # Main case: intermediate invariant with coverage carrying an extra scope column.
    inter_dir = make_pack(tmp_path, "intermediate", [
        COVERAGE_RULE,
        violation_rule([{"invariant": "intermediate", "within": {"relation": "alpha_coverage"}}]),
    ])
    try:
        model = pack.read(inter_dir)
    except pack.CompileError as error:
        raise MissingIntermediateInvariantLowering(str(error)) from error

    assert len(model.intermediate_invariants) == 1
    [entry] = model.intermediate_invariants
    assert entry.relation == "missing_guard"
    assert entry.coverage_relation == "alpha_coverage"
    assert tuple(entry.key_binding) == (("item", "item"),)

    files = emit.compile_pack(model)
    ir = json.loads(files["ir/rules.json"])
    violation_rels = [rel for rel in ir["relations"] if rel["name"] == "missing_guard"]
    assert len(violation_rels) == 1 and violation_rels[0].get("invariant") is True

    # Counter-case 2: missing coverage relation is refused with CompileError.
    missing_dir = make_pack(tmp_path, "missing_cov", [
        violation_rule([{"invariant": "intermediate", "within": {"relation": "no_such_coverage"}}]),
    ])
    with pytest.raises(pack.CompileError):
        pack.read(missing_dir)

    # Counter-case 3: incompatible coverage key column type (Beta instead of Alpha) is refused with CompileError.
    bad_cov = {
        "rule": "wrong_coverage",
        "columns": [{"name": "item", "type": "Beta"}],
        "when": {"call": ["beta", [{"path": ["item"]}]]},
    }
    bad_dir = make_pack(tmp_path, "wrong_cov", [
        bad_cov,
        violation_rule([{"invariant": "intermediate", "within": {"relation": "wrong_coverage"}}]),
    ])
    with pytest.raises(pack.CompileError):
        pack.read(bad_dir)
