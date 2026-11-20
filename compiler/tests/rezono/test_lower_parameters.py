"""A row-backed parameter written in Rezono lowers to the parameters and parameter_choice of the calculation
program (decisions/language-calculations.md, section Parameters). The oracle is calc/award.yaml of the
scheme that examples/subsidy imports: two of its rules move to a module form, the rest stays in the YAML file."""

from types import SimpleNamespace

import pytest
import yaml

from calc_packs import (SCHEME, MissingCalculationLowering, calc_ir, definition, derived, examples, form, lit,
                        lowered, path, row_parameter)
from rezono_compiler import pack, rezono_calc, rezono_module
from support import FIXTURE


MOVED = ("income_threshold@2026", "income_limit@2026")


def split(root):
    """The scheme with the two rules of MOVED taken out of calc/award.yaml, and written as a module form."""
    scheme = examples(root) / SCHEME
    award = scheme / "calc" / "award.yaml"
    doc = yaml.safe_load(award.read_bytes())
    doc["rules"] = [rule for rule in doc["rules"] if rule["id"] not in MOVED]
    award.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    values = [
        derived("income_threshold", definition("base_plus_persons", lit("true"), {"arith": [
            "+", path("income_threshold_base"),
            {"arith": ["*", path("household_size", "persons"), path("income_threshold_per_person")]}]})),
        derived("income_limit", definition("threshold_plus_margin", lit("true"),
                                           {"arith": ["+", path("income_threshold"), path("income_margin")]})),
    ]
    parameters = [row_parameter(name) for name in
                  ("income_threshold_base", "income_threshold_per_person", "income_margin")]
    return scheme, parameters, values


def test_lower_parameters(tmp_path):
    expected = calc_ir(examples(tmp_path / "legacy") / SCHEME)
    assert expected["ir/calc.json"]["parameter_choice"]["name"] == "scheme_parameter__name"

    scheme, parameters, values = split(tmp_path / "candidate")
    form(scheme, [*parameters, {"extend": "Application", "derived": values}])
    assert lowered(scheme) == expected

    # Counter-case: the parameters of one program are rows of one source.
    other, parameters, values = split(tmp_path / "other")
    parameters[2] = row_parameter("income_margin", kind="Household", slot="persons", by="id")
    form(other, [*parameters, {"extend": "Application", "derived": values}])
    with pytest.raises(pack.CompileError, match="two parameter sources"):
        calc_ir(other)


def test_parameter_source_unknown_kind_reports_located_r050_and_collects_errors():
    """An unresolved kind in a row-backed parameter source produces a located R050 and still collects later errors."""
    model = pack.read(FIXTURE)
    decls = [
        {
            "param": "rate",
            "type": "Int",
            "source": {"kind": "MissingKind", "slot": "size", "nameSlot": "title"},
        },
        {
            "param": "rate",
            "type": "Int",
            "source": {"kind": "Alpha", "slot": "size", "nameSlot": "title"},
        },
    ]
    body = {"rezono": "0", "pack": model.meta["name"], "use": [], "decls": decls}
    spans = [
        {"at": at, "line": "10" if at.startswith("/decls/0") else "11", "start": "0", "end": "1"}
        for at in rezono_module.place_pointers(body)
    ]
    mod = SimpleNamespace(
        pack=model.meta["name"],
        pack_dir=FIXTURE,
        rel="rezono/params.rezono",
        form={"format": rezono_module.IDENTIFIER_FORMAT, "module": body, "spans": spans},
    )
    with pytest.raises(pack.CompileError) as caught:
        rezono_calc.lower_module(model, mod, {})
    diags = caught.value.diagnostics
    assert [d.code for d in diags] == ["R050", "R050"]
    assert "minimal/rezono/params.rezono:10:" in diags[0].message
    assert "MissingKind" in diags[0].message
    assert "minimal/rezono/params.rezono:11:" in diags[1].message
    assert "declared twice" in diags[1].message
