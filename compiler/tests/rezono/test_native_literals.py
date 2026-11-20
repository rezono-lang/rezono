"""Native literal flag validation applies across rezono.module/3, rezono.module/4, and rezono.module/5."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from rezono_compiler import rezono_module
from rezono_compiler.native_literals import native_literal_errors


def _spans(module: dict) -> list[dict]:
    return [
        {"at": pointer, "line": "1", "start": "0", "end": "1"}
        for pointer in rezono_module.place_pointers(module)
    ]


def _form(fmt: str, decls: list[dict], *, rezono: str = "0") -> dict:
    module = {"rezono": rezono, "pack": "minimal", "use": [], "decls": decls}
    return {"format": fmt, "module": module, "spans": _spans(module)}


BASE_RULE = {
    "rule": "marked",
    "columns": [{"name": "item", "type": "Alpha"}],
    "options": [{"extend": True}, {"invariant": True}, {"absence": True}],
}

CLAUSE_RULE = {
    "rule": "marked",
    "args": [{"path": ["x"]}],
    "when": {"call": ["Alpha.near", [{"wildcard": True}, {"path": ["x"]}]]},
}

INTERMEDIATE_RULE = {
    "rule": "missing_guard",
    "columns": [{"name": "item", "type": "Alpha"}],
    "options": [{"invariant": "intermediate", "within": {"relation": "alpha_coverage"}}],
    "when": {"in": [{"path": ["item"]}, {"kind": "Alpha"}]},
}

STEP_DECL = {
    "step": "install_beta",
    "columns": [{"name": "item", "type": "Alpha"}],
    "when": {"in": [{"path": ["item"]}, {"kind": "Alpha"}]},
    "forbid": [{
        "pattern": {"call": ["active_beta", [{"wildcard": True}, {"path": ["item"]}]]},
        "within": {"call": ["beta_inventory", [{"path": ["item"]}]]},
    }],
    "effect": {
        "operation": "item_install",
        "changes": [{"retract_row": {"kind": "Beta", "key": {"path": ["item"]}}}],
    },
    "confirm": {
        "reader": {"call": ["beta_readback", [{"path": ["item"]}]]},
        "token": {"path": ["item"]},
    },
}


@pytest.mark.parametrize("fmt", ["rezono.module/3", "rezono.module/4", "rezono.module/5"])
def test_invalid_native_literals_fail_across_supported_versions(fmt: str):
    rezono_ver = "1" if fmt == "rezono.module/5" else "0"

    bad_wildcard = deepcopy(CLAUSE_RULE)
    bad_wildcard["when"]["call"][1][0]["wildcard"] = False
    errors = native_literal_errors(_form(fmt, [BASE_RULE, bad_wildcard], rezono=rezono_ver))
    assert errors, f"expected wildcard error for {fmt}"
    assert any("wildcard" in err for err in errors)

    bad_args_wildcard = deepcopy(CLAUSE_RULE)
    bad_args_wildcard["args"] = [{"wildcard": "true"}]
    errors = native_literal_errors(_form(fmt, [BASE_RULE, bad_args_wildcard], rezono=rezono_ver))
    assert any("wildcard" in err for err in errors)

    for flag in ("extend", "invariant", "absence"):
        bad_head = deepcopy(BASE_RULE)
        bad_head["options"] = [{flag: False}]
        errors = native_literal_errors(_form(fmt, [bad_head], rezono=rezono_ver))
        assert errors, f"expected {flag} error for {fmt}"
        assert any(flag in err for err in errors)


def test_rezono_module_4_read_form_rejects_invalid_literals(tmp_path: Path):
    bad_clause = deepcopy(CLAUSE_RULE)
    bad_clause["when"]["call"][1][0]["wildcard"] = False
    bad_form = _form("rezono.module/4", [INTERMEDIATE_RULE, bad_clause])

    form_path = tmp_path / "rezono" / "rules.json"
    form_path.parent.mkdir(parents=True)
    form_path.write_text(json.dumps(bad_form), encoding="utf-8")

    declared = rezono_module.Declared("rezono/rules.rezono", "rezono/rules.json", "facts")
    errors: list[str] = []
    assert rezono_module.read_form(tmp_path, declared, errors) is None
    assert any("wildcard" in err for err in errors)


def test_rezono_module_4_step_forbid_wildcard_checked():
    valid_step_form = _form("rezono.module/4", [STEP_DECL])
    assert native_literal_errors(valid_step_form) == []

    bad_step = deepcopy(STEP_DECL)
    bad_step["forbid"][0]["pattern"]["call"][1][0]["wildcard"] = False
    errors = native_literal_errors(_form("rezono.module/4", [bad_step]))
    assert any("wildcard" in err for err in errors)


def test_intermediate_invariant_allowed_in_v4_and_v5_but_not_v3():
    assert native_literal_errors(_form("rezono.module/4", [INTERMEDIATE_RULE])) == []
    assert native_literal_errors(_form("rezono.module/5", [INTERMEDIATE_RULE], rezono="1")) == []
    assert native_literal_errors(_form("rezono.module/3", [INTERMEDIATE_RULE]))

    bad_intermediate = deepcopy(INTERMEDIATE_RULE)
    bad_intermediate["options"] = [{"invariant": False, "within": {"relation": "alpha_coverage"}}]
    assert native_literal_errors(_form("rezono.module/4", [bad_intermediate]))

    missing_within = deepcopy(INTERMEDIATE_RULE)
    missing_within["options"] = [{"invariant": "intermediate"}]
    assert native_literal_errors(_form("rezono.module/4", [missing_within]))


def test_non_native_and_malformed_format_values_are_ignored():
    assert native_literal_errors(_form("rezono.module/1", [BASE_RULE])) == []
    assert native_literal_errors(_form("rezono.module/2", [BASE_RULE])) == []
    assert native_literal_errors({"format": ["rezono.module/4"]}) == []
    assert native_literal_errors("not a form") == []
