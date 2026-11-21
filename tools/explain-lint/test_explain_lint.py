"""Verify explain_lint inspects native .rezono modules for fold marks and rule IR."""

import importlib.util
import json
from pathlib import Path

import yaml


def _load_explain_lint():
    spec = importlib.util.spec_from_file_location(
        "explain_lint", Path(__file__).with_name("explain_lint.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXPLAIN_LINT = _load_explain_lint()

UNFOLDED_MOD2_TEXT = """\
rezono 0
pack sample

schema sample
  iri "https://rezono.example/sample"
  language en
  import "linkml:types"
  default range Text
  annotation layer = "facts"

kind Alpha world closed

kind Beta world closed
  first: Alpha
  second: Alpha

rules core
  | .decl ends(a: symbol, b: symbol)
  | ends(a, b) :- beta__first(e, a), beta__second(e, b).
  | .decl linked(a: symbol, b: symbol)
  | linked(a, b) :- ends(a, b).
  | .output linked
"""

UNFOLDED_MOD2_FORM = {
    "format": "rezono.module/2",
    "module": {
        "annotations": {"layer": "facts"},
        "decls": [
            {"derived": [], "kind": "Alpha", "slots": [], "world": "closed"},
            {
                "derived": [],
                "kind": "Beta",
                "slots": [
                    {"slot": "first", "type": "Alpha"},
                    {"slot": "second", "type": "Alpha"},
                ],
                "world": "closed",
            },
            {
                "lines": [
                    ".decl ends(a: symbol, b: symbol)",
                    "ends(a, b) :- beta__first(e, a), beta__second(e, b).",
                    ".decl linked(a: symbol, b: symbol)",
                    "linked(a, b) :- ends(a, b).",
                    ".output linked",
                ],
                "rules": "core",
            },
        ],
        "defaultRange": "Text",
        "imports": ["linkml:types"],
        "iri": "https://rezono.example/sample",
        "language": "en",
        "pack": "sample",
        "rezono": "0",
        "schema": "sample",
        "use": [],
    },
    "spans": [
        {"at": "", "end": "38", "line": "4", "start": "32"},
        {"at": "/decls/0", "end": "183", "line": "11", "start": "178"},
        {"at": "/decls/1", "end": "209", "line": "13", "start": "205"},
        {"at": "/decls/1/slots/0", "end": "231", "line": "14", "start": "226"},
        {"at": "/decls/1/slots/1", "end": "248", "line": "15", "start": "242"},
        {"at": "/decls/2", "end": "269", "line": "17", "start": "265"},
    ],
}

FOLDED_MOD2_TEXT = """\
rezono 0
pack sample

schema sample
  iri "https://rezono.example/sample"
  language en
  import "linkml:types"
  default range Text
  annotation layer = "facts"

kind Alpha world closed

kind Beta world closed
  annotation explain = "fold"
  first: Alpha
  second: Alpha

rules core
  | // @explain fold
  | .decl ends(a: symbol, b: symbol)
  | ends(a, b) :- beta__first(e, a), beta__second(e, b).
  | .decl linked(a: symbol, b: symbol)
  | linked(a, b) :- ends(a, b).
  | .output linked
"""

FOLDED_MOD2_FORM = {
    "format": "rezono.module/2",
    "module": {
        "annotations": {"layer": "facts"},
        "decls": [
            {"derived": [], "kind": "Alpha", "slots": [], "world": "closed"},
            {
                "annotations": {"explain": "fold"},
                "derived": [],
                "kind": "Beta",
                "slots": [
                    {"slot": "first", "type": "Alpha"},
                    {"slot": "second", "type": "Alpha"},
                ],
                "world": "closed",
            },
            {
                "lines": [
                    "// @explain fold",
                    ".decl ends(a: symbol, b: symbol)",
                    "ends(a, b) :- beta__first(e, a), beta__second(e, b).",
                    ".decl linked(a: symbol, b: symbol)",
                    "linked(a, b) :- ends(a, b).",
                    ".output linked",
                ],
                "rules": "core",
            },
        ],
        "defaultRange": "Text",
        "imports": ["linkml:types"],
        "iri": "https://rezono.example/sample",
        "language": "en",
        "pack": "sample",
        "rezono": "0",
        "schema": "sample",
        "use": [],
    },
    "spans": [
        {"at": "", "end": "38", "line": "4", "start": "32"},
        {"at": "/decls/0", "end": "183", "line": "11", "start": "178"},
        {"at": "/decls/1", "end": "209", "line": "13", "start": "205"},
        {"at": "/decls/1/slots/0", "end": "262", "line": "15", "start": "257"},
        {"at": "/decls/1/slots/1", "end": "279", "line": "16", "start": "273"},
        {"at": "/decls/2", "end": "300", "line": "18", "start": "296"},
    ],
}

MOD3_TEXT = """\
rezono 0
pack sample
rule ends(a: Alpha, b: Alpha) explain fold when a in Alpha and b in Alpha
"""

MOD3_FORM = {
    "format": "rezono.module/3",
    "module": {
        "decls": [
            {
                "columns": [
                    {"name": "a", "type": "Alpha"},
                    {"name": "b", "type": "Alpha"},
                ],
                "options": [{"explain": "fold"}],
                "rule": "ends",
                "when": {
                    "and": [
                        {"in": [{"path": ["a"]}, {"kind": "Alpha"}]},
                        {"in": [{"path": ["b"]}, {"kind": "Alpha"}]},
                    ]
                },
            }
        ],
        "pack": "sample",
        "rezono": "0",
        "use": [],
    },
    "spans": [
        {"at": "/decls/0", "end": "32", "line": "3", "start": "28"},
        {"at": "/decls/0/columns/0", "end": "34", "line": "3", "start": "33"},
        {"at": "/decls/0/columns/1", "end": "44", "line": "3", "start": "43"},
        {"at": "/decls/0/options/0", "end": "65", "line": "3", "start": "53"},
        {"at": "/decls/0/when", "end": "96", "line": "3", "start": "71"},
        {"at": "/decls/0/when/and/0", "end": "81", "line": "3", "start": "71"},
        {"at": "/decls/0/when/and/0/in/0", "end": "72", "line": "3", "start": "71"},
        {"at": "/decls/0/when/and/0/in/1", "end": "81", "line": "3", "start": "76"},
        {"at": "/decls/0/when/and/1", "end": "96", "line": "3", "start": "86"},
        {"at": "/decls/0/when/and/1/in/0", "end": "87", "line": "3", "start": "86"},
        {"at": "/decls/0/when/and/1/in/1", "end": "96", "line": "3", "start": "91"},
    ],
}

MOD5_TEXT = """\
rezono 1
pack sample
kind Alpha
kind Beta
  annotation explain = "fold"
  first: Alpha
  second: Alpha
derived ends(a: Alpha, b: Alpha): Bool explain fold = true
"""

MOD5_FORM = {
    "format": "rezono.module/5",
    "module": {
        "decls": [
            {"derived": [], "kind": "Alpha", "slots": []},
            {
                "annotations": {"explain": "fold"},
                "derived": [],
                "kind": "Beta",
                "slots": [
                    {"slot": "first", "type": "Alpha"},
                    {"slot": "second", "type": "Alpha"},
                ],
            },
            {
                "derived": "ends",
                "options": [{"explain": "fold"}],
                "params": [
                    {"name": "a", "type": "Alpha"},
                    {"name": "b", "type": "Alpha"},
                ],
                "type": "Bool",
                "value": {"lit": "true"},
            },
        ],
        "pack": "sample",
        "rezono": "1",
        "use": [],
    },
    "spans": [
        {"at": "/decls/0", "end": "33", "line": "3", "start": "28"},
        {"at": "/decls/1", "end": "44", "line": "4", "start": "40"},
        {"at": "/decls/1/slots/0", "end": "84", "line": "6", "start": "79"},
        {"at": "/decls/1/slots/1", "end": "101", "line": "7", "start": "95"},
        {"at": "/decls/2", "end": "122", "line": "8", "start": "118"},
        {"at": "/decls/2/options/0", "end": "161", "line": "8", "start": "149"},
        {"at": "/decls/2/params/0", "end": "124", "line": "8", "start": "123"},
        {"at": "/decls/2/params/1", "end": "134", "line": "8", "start": "133"},
        {"at": "/decls/2/value", "end": "168", "line": "8", "start": "164"},
    ],
}

BUNDLE = {
    "kinds": [
        {"id": "alpha", "class": "Alpha", "table": "alpha"},
        {"id": "beta", "class": "Beta", "table": "beta"},
    ],
    "arrows": [
        {"table": "beta__first", "kind": "beta", "target": "alpha"},
        {"table": "beta__second", "kind": "beta", "target": "alpha"},
    ],
    "attributes": [],
    "channels": {},
    "questions": [],
    "checks": [],
}

RULE_IR = {
    "relations": [
        {"name": "ends", "role": "derived"},
        {"name": "linked", "role": "derived"},
    ],
    "rules": [
        {
            "module": "core",
            "head": {"relation": "ends", "terms": ["?a", "?b"]},
            "body": [
                {"relation": "beta__first", "terms": ["?e", "?a"]},
                {"relation": "beta__second", "terms": ["?e", "?b"]},
            ],
        },
        {
            "module": "core",
            "head": {"relation": "linked", "terms": ["?a", "?b"]},
            "body": [
                {"relation": "alpha", "terms": ["?a"]},
                {"relation": "alpha", "terms": ["?b"]},
                {"relation": "ends", "terms": ["?a", "?b"]},
            ],
        },
    ],
}


def _write_native_pack(
    pack_dir: Path,
    source_text: str,
    form_doc: dict,
    *,
    write_bundle: bool = True,
    write_rules: bool = True,
) -> Path:
    (pack_dir / "rezono").mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "sample",
                "version": "0.1.0",
                "default_language": "en",
                "imports": [],
                "rezono": [
                    {
                        "module": "rezono/core.rezono",
                        "form": "rezono/core.json",
                        "layer": "facts",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (pack_dir / "rezono" / "core.rezono").write_text(
        source_text, encoding="utf-8", newline="\n"
    )
    (pack_dir / "rezono" / "core.json").write_text(
        json.dumps(form_doc, sort_keys=True), encoding="utf-8", newline="\n"
    )
    if write_bundle:
        bundle_path = pack_dir / "expected" / "compiled" / "bundle" / "schema-bundle.json"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(json.dumps(BUNDLE), encoding="utf-8")
    if write_rules:
        ir_path = pack_dir / "expected" / "compiled" / "ir" / "rules.json"
        ir_path.parent.mkdir(parents=True, exist_ok=True)
        ir_path.write_text(json.dumps(RULE_IR), encoding="utf-8")
    return pack_dir


def test_folded_and_lint_inspect_native_rezono_modules(tmp_path):
    unfolded = _write_native_pack(
        tmp_path / "unfolded", UNFOLDED_MOD2_TEXT, UNFOLDED_MOD2_FORM
    )
    assert EXPLAIN_LINT.folded(unfolded) == set()
    assert sorted(f.what for f in EXPLAIN_LINT.lint(unfolded, tmp_path).findings) == [
        "helper relation ends is not folded (explain: fold)",
        "kind beta is only reached through joins and is not folded (explain: fold)",
    ]

    folded = _write_native_pack(tmp_path / "folded", FOLDED_MOD2_TEXT, FOLDED_MOD2_FORM)
    assert EXPLAIN_LINT.folded(folded) == {"Beta", "ends"}
    assert EXPLAIN_LINT.lint(folded, tmp_path).findings == ()


def test_folded_reads_native_rule_and_rezono_1_derived_options(tmp_path):
    mod3 = _write_native_pack(
        tmp_path / "mod3", MOD3_TEXT, MOD3_FORM, write_bundle=False, write_rules=False
    )
    assert EXPLAIN_LINT.folded(mod3) == {"ends"}

    mod5 = _write_native_pack(
        tmp_path / "mod5", MOD5_TEXT, MOD5_FORM, write_bundle=False, write_rules=False
    )
    assert EXPLAIN_LINT.folded(mod5) == {"Beta", "ends"}


def test_products_requires_rule_ir_for_native_rezono_rules(tmp_path, monkeypatch):
    pack_dir = _write_native_pack(
        tmp_path / "missing-ir",
        UNFOLDED_MOD2_TEXT,
        UNFOLDED_MOD2_FORM,
        write_bundle=True,
        write_rules=False,
    )
    invoked: list[list[str]] = []
    real_run = EXPLAIN_LINT.subprocess.run

    def fake_compile(cmd, *args, **kwargs):
        if len(cmd) >= 4 and cmd[1:4] == ["-m", "rezono_compiler", "compile"]:
            invoked.append(cmd)
            out = Path(cmd[-1])
            (out / "bundle").mkdir(parents=True, exist_ok=True)
            (out / "ir").mkdir(parents=True, exist_ok=True)
            (out / "bundle" / "schema-bundle.json").write_text(
                json.dumps(BUNDLE), encoding="utf-8"
            )
            (out / "ir" / "rules.json").write_text(json.dumps(RULE_IR), encoding="utf-8")
            return None
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(EXPLAIN_LINT.subprocess, "run", fake_compile)
    findings = sorted(f.what for f in EXPLAIN_LINT.lint(pack_dir, tmp_path).findings)
    assert len(invoked) == 1
    assert findings == [
        "helper relation ends is not folded (explain: fold)",
        "kind beta is only reached through joins and is not folded (explain: fold)",
    ]


KIND_DERIVED_FOLDED_TEXT = """\
rezono 1
pack sample
kind Alpha
kind Beta
  annotation explain = "fold"
  first: Alpha
  second: Alpha
  derived ends: Bool explain fold = true
"""

KIND_DERIVED_FOLDED_FORM = {
    "format": "rezono.module/5",
    "module": {
        "decls": [
            {"derived": [], "kind": "Alpha", "slots": []},
            {
                "annotations": {"explain": "fold"},
                "derived": [
                    {
                        "derived": "ends",
                        "options": [{"explain": "fold"}],
                        "type": "Bool",
                        "value": {"lit": "true"},
                    }
                ],
                "kind": "Beta",
                "slots": [
                    {"slot": "first", "type": "Alpha"},
                    {"slot": "second", "type": "Alpha"},
                ],
            },
        ],
        "pack": "sample",
        "rezono": "1",
        "use": [],
    },
    "spans": [
        {"at": "/decls/0", "end": "31", "line": "3", "start": "26"},
        {"at": "/decls/1", "end": "41", "line": "4", "start": "37"},
        {"at": "/decls/1/derived/0", "end": "117", "line": "8", "start": "113"},
        {"at": "/decls/1/derived/0/options/0", "end": "136", "line": "8", "start": "124"},
        {"at": "/decls/1/derived/0/value", "end": "143", "line": "8", "start": "139"},
        {"at": "/decls/1/slots/0", "end": "79", "line": "6", "start": "74"},
        {"at": "/decls/1/slots/1", "end": "95", "line": "7", "start": "89"},
    ],
}

KIND_DERIVED_UNFOLDED_TEXT = """\
rezono 1
pack sample
kind Alpha
kind Beta
  first: Alpha
  second: Alpha
  derived ends: Bool = true
"""

KIND_DERIVED_UNFOLDED_FORM = {
    "format": "rezono.module/5",
    "module": {
        "decls": [
            {"derived": [], "kind": "Alpha", "slots": []},
            {
                "derived": [
                    {
                        "derived": "ends",
                        "type": "Bool",
                        "value": {"lit": "true"},
                    }
                ],
                "kind": "Beta",
                "slots": [
                    {"slot": "first", "type": "Alpha"},
                    {"slot": "second", "type": "Alpha"},
                ],
            },
        ],
        "pack": "sample",
        "rezono": "1",
        "use": [],
    },
    "spans": [
        {"at": "/decls/0", "end": "31", "line": "3", "start": "26"},
        {"at": "/decls/1", "end": "41", "line": "4", "start": "37"},
        {"at": "/decls/1/derived/0", "end": "87", "line": "7", "start": "83"},
        {"at": "/decls/1/derived/0/value", "end": "100", "line": "7", "start": "96"},
        {"at": "/decls/1/slots/0", "end": "49", "line": "5", "start": "44"},
        {"at": "/decls/1/slots/1", "end": "65", "line": "6", "start": "59"},
    ],
}

EXTEND_DERIVED_FOLDED_TEXT = """\
rezono 1
pack sample
kind Alpha
kind Beta
  first: Alpha
  second: Alpha
extend Beta
  derived ends: Bool explain fold = true
"""

EXTEND_DERIVED_FOLDED_FORM = {
    "format": "rezono.module/5",
    "module": {
        "decls": [
            {"derived": [], "kind": "Alpha", "slots": []},
            {
                "derived": [],
                "kind": "Beta",
                "slots": [
                    {"slot": "first", "type": "Alpha"},
                    {"slot": "second", "type": "Alpha"},
                ],
            },
            {
                "derived": [
                    {
                        "derived": "ends",
                        "options": [{"explain": "fold"}],
                        "type": "Bool",
                        "value": {"lit": "true"},
                    }
                ],
                "extend": "Beta",
            },
        ],
        "pack": "sample",
        "rezono": "1",
        "use": [],
    },
    "spans": [
        {"at": "/decls/0", "end": "31", "line": "3", "start": "26"},
        {"at": "/decls/1", "end": "41", "line": "4", "start": "37"},
        {"at": "/decls/1/slots/0", "end": "49", "line": "5", "start": "44"},
        {"at": "/decls/1/slots/1", "end": "65", "line": "6", "start": "59"},
        {"at": "/decls/2", "end": "84", "line": "7", "start": "80"},
        {"at": "/decls/2/derived/0", "end": "99", "line": "8", "start": "95"},
        {"at": "/decls/2/derived/0/options/0", "end": "118", "line": "8", "start": "106"},
        {"at": "/decls/2/derived/0/value", "end": "125", "line": "8", "start": "121"},
    ],
}


def test_kind_and_extend_nested_derived_fold_marks_and_rule_ir(tmp_path, monkeypatch):
    # _decl_has_rules recognizes non-empty derived lists on kind and extend declarations,
    # while ignoring kinds/extends with an empty derived list.
    assert not EXPLAIN_LINT._decl_has_rules({"kind": "Alpha", "derived": [], "slots": []})
    assert EXPLAIN_LINT._decl_has_rules(KIND_DERIVED_UNFOLDED_FORM["module"]["decls"][1])
    assert EXPLAIN_LINT._decl_has_rules(EXTEND_DERIVED_FOLDED_FORM["module"]["decls"][2])

    # Folded nested derived items under kind and extend are extracted via options and annotations.
    kind_folded = _write_native_pack(
        tmp_path / "kind-folded", KIND_DERIVED_FOLDED_TEXT, KIND_DERIVED_FOLDED_FORM
    )
    assert EXPLAIN_LINT.folded(kind_folded) == {"Beta", "ends"}
    assert EXPLAIN_LINT.lint(kind_folded, tmp_path).findings == ()

    extend_folded = _write_native_pack(
        tmp_path / "extend-folded",
        EXTEND_DERIVED_FOLDED_TEXT,
        EXTEND_DERIVED_FOLDED_FORM,
        write_bundle=False,
        write_rules=False,
    )
    assert EXPLAIN_LINT.folded(extend_folded) == {"ends"}

    # Annotation-based fold marks on nested derived items and table-backed extend items are also recognized.
    annotated_form = {
        "module": {
            "decls": [
                {
                    "kind": "Beta",
                    "derived": [
                        {"derived": "via_ann", "annotations": {"explain": "fold"}},
                        {"derived": "plain"},
                    ],
                },
                {
                    "extend": "Beta",
                    "derived": [
                        {"derived": "band", "options": [{"explain": "fold"}], "table": {"table": "unique"}},
                    ],
                },
            ]
        }
    }
    assert EXPLAIN_LINT._fold_marks_from_form(annotated_form) == {"via_ann", "band", "beta_band"}

    # A pack whose only rule-bearing decl is a kind with a non-empty derived list must
    # require ir/rules.json and trigger compilation when it is absent.
    missing_ir = _write_native_pack(
        tmp_path / "kind-derived-missing-ir",
        KIND_DERIVED_UNFOLDED_TEXT,
        KIND_DERIVED_UNFOLDED_FORM,
        write_bundle=True,
        write_rules=False,
    )
    invoked: list[list[str]] = []
    real_run = EXPLAIN_LINT.subprocess.run

    def fake_compile(cmd, *args, **kwargs):
        if len(cmd) >= 4 and cmd[1:4] == ["-m", "rezono_compiler", "compile"]:
            invoked.append(cmd)
            out = Path(cmd[-1])
            (out / "bundle").mkdir(parents=True, exist_ok=True)
            (out / "ir").mkdir(parents=True, exist_ok=True)
            (out / "bundle" / "schema-bundle.json").write_text(
                json.dumps(BUNDLE), encoding="utf-8"
            )
            (out / "ir" / "rules.json").write_text(json.dumps(RULE_IR), encoding="utf-8")
            return None
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(EXPLAIN_LINT.subprocess, "run", fake_compile)
    findings = sorted(f.what for f in EXPLAIN_LINT.lint(missing_ir, tmp_path).findings)
    assert len(invoked) == 1
    assert findings == [
        "helper relation ends is not folded (explain: fold)",
        "kind beta is only reached through joins and is not folded (explain: fold)",
    ]
