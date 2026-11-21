"""Open-world existential compilation, cardinality bound validation, diagnostic source pointers,
and fact-row-only module recognition for `rezono 1` (decisions/language-requirements.md)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from expression_packs import register
from rezono_compiler import emit, pack, rezono_module, rules
from support import FIXTURE


def _write_module5_pack(directory: Path, decls: list[dict]) -> Path:
    """Create a minimal rezono 1 pack from a rezono.module/5 declaration list."""
    directory = Path(shutil.copytree(FIXTURE, directory))
    folder = directory / "rezono"
    folder.mkdir()
    module_doc = {"rezono": "1", "pack": "minimal", "use": [], "decls": decls}
    spans = [
        {"at": pointer, "line": "1", "start": "0", "end": "1"}
        for pointer in rezono_module.place_pointers(module_doc)
    ]
    form_doc = {
        "format": rezono_module.REZONO_1_FORMAT,
        "module": module_doc,
        "spans": spans,
    }
    (folder / "requirements.rezono").write_text("rezono 1\npack minimal\n", encoding="utf-8", newline="\n")
    (folder / "requirements.json").write_text(json.dumps(form_doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    register(
        directory,
        {"module": "rezono/requirements.rezono", "form": "rezono/requirements.json", "layer": "facts"},
    )
    return directory


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-requirements.md: pure unbounded existential `require` over a `world open` "
        "target must compile cleanly via pack.read without failing with functional_reads_open"
    ),
)
def test_require_unbounded_exists_over_open_world_target_compiles_without_functional_reads_open(tmp_path):
    directory = _write_module5_pack(
        tmp_path / "open_target",
        [
            {"kind": "Service", "world": "closed", "slots": []},
            {"kind": "UnscopedObs", "world": "open", "slots": []},
            {
                "require": "svc_has_obs",
                "params": [{"name": "s", "type": "Service"}],
                "exists": [{"binder": "u", "kind": "UnscopedObs"}],
            },
        ],
    )

    try:
        model = pack.read(directory)
        files = emit.compile_pack(model)
        ir_doc = json.loads(files["ir/rules.json"])
        prog = rules.load(ir_doc)
    except (pack.CompileError, rules.IRError) as exc:
        raise AssertionError(
            f"unbounded existential over open-world target failed to compile cleanly: {exc}"
        ) from exc

    assert "svc_has_obs" in prog.relations
    assert prog.relations["svc_has_obs"].role == "functional"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-requirements.md: require lowering must refuse non-positive/negative/unknown "
        "cardinality bounds with R000 and point non-text source diagnostics at #/decls/<idx>/source"
    ),
)
def test_require_rejects_non_positive_or_unknown_bounds_and_points_source_errors(tmp_path):
    base_kinds = [
        {"kind": "Service", "world": "closed", "slots": []},
        {"kind": "Replica", "world": "closed", "slots": []},
    ]

    invalid_bounds = [
        ("at_least_zero", {"op": "at_least", "count": "0"}),
        ("at_most_negative", {"op": "at_most", "count": "-1"}),
        ("exactly_negative", {"op": "exactly", "count": "-2"}),
        ("unknown_op", {"op": "between", "count": "1"}),
    ]

    bound_problems: list[str] = []
    for label, bound in invalid_bounds:
        directory = _write_module5_pack(
            tmp_path / label,
            [
                *base_kinds,
                {
                    "require": f"req_{label}",
                    "params": [{"name": "s", "type": "Service"}],
                    "exists": [{"binder": "r", "kind": "Replica", "bound": bound}],
                },
            ],
        )
        try:
            emit.compile_pack(pack.read(directory))
        except pack.CompileError as exc:
            codes = [diag.code for diag in getattr(exc, "diagnostics", ())]
            if "R000" not in codes:
                bound_problems.append(f"{label}: expected R000 diagnostic, got codes={codes!r} ({exc})")
        except Exception as exc:
            bound_problems.append(f"{label}: expected CompileError(R000), got {type(exc).__name__}: {exc}")
        else:
            bound_problems.append(f"{label}: compiled silently instead of raising CompileError(R000)")

    # Non-text `source` on a `require` declaration (at decl index 2) must report R000 at #/decls/2/source.
    source_dir = _write_module5_pack(
        tmp_path / "non_text_source",
        [
            *base_kinds,
            {
                "require": "req_bad_source",
                "params": [{"name": "s", "type": "Service"}],
                "exists": [{"binder": "r", "kind": "Replica"}],
                "source": 123,
            },
        ],
    )
    source_problems: list[str] = []
    try:
        emit.compile_pack(pack.read(source_dir))
    except pack.CompileError as exc:
        diags = [(d.code, d.where.partition("#")[2]) for d in getattr(exc, "diagnostics", ())]
        if ("R000", "/decls/2/source") not in diags:
            source_problems.append(f"expected ('R000', '/decls/2/source'), got {diags!r}")
    else:
        source_problems.append("non-text source compiled silently instead of raising CompileError(R000)")

    problems = bound_problems + source_problems
    assert not problems, "; ".join(problems)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-requirements.md: fact_tables_only must recognize modules whose declarations "
        "contain only fact rows alongside optional sources"
    ),
)
def test_fact_tables_only_recognizes_fact_row_only_modules():
    # Negative controls that already hold on main.
    assert rezono_module.fact_tables_only({"pack": "minimal", "decls": []}) is False
    assert rezono_module.fact_tables_only({"pack": "minimal", "decls": [{"source": "s", "fields": []}]}) is False
    assert rezono_module.fact_tables_only(
        {
            "pack": "minimal",
            "decls": [
                {"kind": "Person", "slots": []},
                {"fact": "Person", "id": "p1", "set": [{"slot": "income", "value": "100"}]},
            ],
        }
    ) is False

    # Fact-row-only module must be recognized as fact_tables_only.
    fact_row_only = {
        "pack": "minimal",
        "decls": [
            {"fact": "Person", "id": "p1", "set": [{"slot": "income", "value": "100"}]}
        ],
    }
    assert rezono_module.fact_tables_only(fact_row_only) is True
