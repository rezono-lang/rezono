"""A rule clause's sentence lowers to its message in the default language, and its source to the bundle's rule entry
(decisions/language-readable-rules.md, section 2). The module text and the expected message line are written from
that decision; the counter-cases are the same rule without a sentence and a sentence that the message file repeats."""

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from expression_packs import ROOT, register
from rezono_compiler import emit, modules, native_rule_lowering, pack, rezono_derived
from support import FIXTURE

KINDS = """rezono 0
pack minimal

kind Offer world closed

kind Product world closed
  offers: Offer*

kind Demand world closed
  product: Product
"""
RULE = "rule offers(d: Demand, o: Offer) when d in Demand and Demand.product(d, p) and Product.offers(p, o)"
SENTENCE = '\n  means "{$d} can buy {$o}."  @ policy#art-3\n'


def compiled(tmp_path: Path, source: str, message_line: str | None = None) -> dict:
    directory = Path(shutil.copytree(FIXTURE, tmp_path / "minimal"))
    if message_line is not None:
        with (directory / "messages/nl.mf2").open("a", encoding="utf-8", newline="\n") as messages:
            messages.write("\n" + message_line + "\n")
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "demand.rezono", folder / "demand.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode != 0:
        raise MissingRuleSentenceLowering(result.stderr)
    register(directory, {"module": "rezono/demand.rezono", "form": "rezono/demand.json", "layer": "facts"})
    return json.loads(emit.compile_pack(pack.read(directory))["bundle/schema-bundle.json"])


def published(bundle: dict) -> tuple[dict, list[str]]:
    [rule] = [rule for rule in bundle["rules"] if rule["relation"] == "offers"]
    [messages] = [entry["resource"] for entry in bundle["messages"] if entry["lang"] == "nl"]
    return rule, messages.splitlines()


class MissingRuleSentenceLowering(AssertionError):
    """The sentence or source of a rule clause was not published as the decision gives, or a repeated one passed."""


def test_lower_rule_sentence(tmp_path):
    # Counter-case: without a sentence the clause keeps its message key and has no source.
    plain, lines = published(compiled(tmp_path / "plain", KINDS + "\n" + RULE + "\n"))
    assert plain["message"] == "rule.offers" and "source" not in plain
    assert not any(line.startswith("rule.offers ") for line in lines)

    authored = KINDS + "\n" + RULE + SENTENCE
    means_line = next(
        number for number, line in enumerate(authored.splitlines(), start=1)
        if line.lstrip().startswith("means ")
    )
    try:
        rule, lines = published(compiled(tmp_path / "sentence", authored))
    except pack.CompileError as error:
        raise MissingRuleSentenceLowering(str(error)) from error
    problems = []
    if rule.get("source") != "policy#art-3":
        problems.append({"rule": rule})
    if "rule.offers = {{{$d} can buy {$o}.}}" not in lines:
        problems.append({"messages": [line for line in lines if line.startswith("rule.")]})
    try:
        compiled(tmp_path / "twice", authored, "rule.offers = {{{$d} buys {$o}.}}")
        problems.append("a sentence that messages/nl.mf2 repeats was not refused")
    except pack.CompileError as error:
        diags = error.diagnostics
        if not (
            len(diags) == 1
            and diags[0].code == "R000"
            and diags[0].where.endswith("/means")
            and diags[0].span is not None
            and diags[0].span[1] == means_line
        ):
            problems.append({
                "expected": {"code": "R000", "where_suffix": "/means", "line": means_line},
                "diagnostics": [diag.doc() for diag in diags],
            })
    if problems:
        raise MissingRuleSentenceLowering(json.dumps(problems, indent=2))


def _place(text: str, needle: str, at: str) -> dict[str, str]:
    start = text.index(needle)
    line = text.count("\n", 0, start) + 1
    return {"at": at, "line": str(line), "start": str(start), "end": str(start + len(needle))}


def _minimal_base(tmp_path: Path) -> tuple[Path, dict, list[modules.Module], pack.Pack]:
    directory = Path(shutil.copytree(FIXTURE, tmp_path))
    meta = yaml.safe_load((directory / "pack.yaml").read_text(encoding="utf-8"))
    errors: list[str] = []
    loaded, _ = modules.load(directory, meta, errors)
    assert not errors, errors
    model = pack.read(directory)
    return directory, meta, loaded, model


def _rezono_module(directory: Path, loaded: list[modules.Module], stem: str, text: str, form: dict) -> tuple[list[modules.Module], modules.Names]:
    from linkml_runtime.linkml_model import SchemaDefinition
    from rezono_compiler.schemaview import SchemaView

    folder = directory / "rezono"
    folder.mkdir(exist_ok=True)
    mod_file = folder / f"{stem}.rezono"
    mod_file.write_text(text, encoding="utf-8", newline="\n")
    empty_sv = SchemaView(SchemaDefinition(id=f"https://rezono.example/minimal/{stem}", name=stem))
    mod = modules.Module(
        id=stem,
        pack="minimal",
        pack_dir=directory,
        file=mod_file,
        sv=empty_sv,
        imports=[loaded[0].id],
        form=form,
    )
    all_mods = [*loaded, mod]
    errors: list[str] = []
    names = modules.Names(all_mods, pack.snake, errors, root="minimal")
    assert not errors, errors
    return all_mods, names


def _lower_rule_note(tmp_path: Path, **extra: object):
    directory, meta, loaded, model = _minimal_base(tmp_path)
    text = (
        "rezono 0\n"
        "pack minimal\n\n"
        "rule tagged(a: Alpha) when a in Alpha\n"
        '  means "{$a} is tagged." @ policy#art-3\n'
    )
    decl: dict[str, object] = {
        "rule": "tagged",
        "columns": [{"name": "a", "type": "Alpha"}],
        "when": {"in": [{"path": ["a"]}, {"kind": "Alpha"}]},
        **extra,
    }
    spans = [
        _place(text, "rule tagged", "/decls/0"),
        _place(text, "a: Alpha", "/decls/0/columns/0"),
        _place(text, "a in Alpha", "/decls/0/when"),
        _place(text, "a in Alpha", "/decls/0/when/in/0"),
        _place(text, "Alpha", "/decls/0/when/in/1"),
    ]
    if "means" in extra:
        spans.append(_place(text, "means", "/decls/0/means"))
    form = {"format": "rezono.module/3", "module": {"rezono": "0", "pack": "minimal", "use": [], "decls": [decl]}, "spans": spans}
    all_mods, names = _rezono_module(directory, loaded, "rule_note", text, form)
    means_line = text.count("\n", 0, text.index("means")) + 1
    return means_line, native_rule_lowering.lower_modules(
        meta, all_mods, {}, names, pack_dir=directory, pack_kinds=model.kinds,
    )


def _lower_derived_note(tmp_path: Path, **extra: object):
    directory, meta, loaded, model = _minimal_base(tmp_path)
    text = (
        "rezono 1\n"
        "pack minimal\n\n"
        'derived titled(a: Alpha): Bool = a.title = "ok"\n'
        '  means "{$a} is titled." @ policy#art-3\n'
    )
    decl: dict[str, object] = {
        "derived": "titled",
        "params": [{"name": "a", "type": "Alpha"}],
        "type": "Bool",
        "value": {"cmp": ["=", {"path": ["a", "title"]}, {"lit": '"ok"'}]},
        **extra,
    }
    spans = [
        _place(text, "derived titled", "/decls/0"),
        _place(text, "a: Alpha", "/decls/0/params/0"),
        _place(text, 'a.title = "ok"', "/decls/0/value"),
    ]
    if "means" in extra:
        spans.append(_place(text, "means", "/decls/0/means"))
    form = {"format": "rezono.module/5", "module": {"rezono": "1", "pack": "minimal", "use": [], "decls": [decl]}, "spans": spans}
    all_mods, names = _rezono_module(directory, loaded, "derived_note", text, form)
    means_line = text.count("\n", 0, text.index("means")) + 1
    return means_line, rezono_derived.lower_pack(meta["name"], all_mods, names, model)


def _single_refusal(call) -> tuple[object | None, str | None]:
    try:
        call()
    except pack.CompileError as error:
        if len(error.diagnostics) != 1:
            return None, f"expected 1 diagnostic, got {[d.doc() for d in error.diagnostics]}"
        return error.diagnostics[0], None
    return None, "non-text note member was accepted instead of refused"


def _native_rule_lowering_duplicates_note_validation() -> list[str]:
    source = (ROOT / "compiler/rezono_compiler/native_rule_lowering.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports_derived = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module and node.module.endswith("rezono_derived")) or any(
                alias.name == "rezono_derived" for alias in node.names
            ):
                imports_derived = True
        elif isinstance(node, ast.Import):
            if any(alias.name.endswith("rezono_derived") for alias in node.names):
                imports_derived = True
    problems: list[str] = []
    if not imports_derived:
        problems.append("native_rule_lowering.py does not import rezono_derived for shared note validation")
    lower_decl = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "lower_declaration"
    )
    for node in ast.walk(lower_decl):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "str"
        ):
            problems.append(f"native_rule_lowering.lower_declaration duplicates str validation at line {node.lineno}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "refuse" and len(node.args) >= 2:
            pointer = ast.unparse(node.args[1])
            if "/means" in pointer or "/source" in pointer:
                problems.append(f"native_rule_lowering.lower_declaration duplicates refuse({pointer}) at line {node.lineno}")
    return problems


def test_unify_note_validation_for_rules_and_derived(tmp_path):
    # Counter-cases: valid text means and source lower cleanly for both rule clauses and derived declarations.
    rule_means_line, [native_src] = _lower_rule_note(tmp_path / "ok-rule", means="{$a} is tagged.", source="policy#art-3")
    assert len(native_src.notes) == 1 and native_src.notes[0] is not None
    assert native_src.notes[0].means == "{$a} is tagged."
    assert native_src.notes[0].source == "policy#art-3"
    assert native_src.notes[0].at == "/decls/0/means"
    assert native_src.notes[0].line == rule_means_line

    derived_means_line, lowered = _lower_derived_note(tmp_path / "ok-derived", means="{$a} is titled.", source="policy#art-3")
    derived_note = lowered.notes["titled"]
    assert derived_note.means == "{$a} is titled."
    assert derived_note.source == "policy#art-3"
    assert derived_note.at == "/decls/0/means"
    assert derived_note.line == derived_means_line

    problems: list[str] = []

    rule_means_diag, err = _single_refusal(lambda: _lower_rule_note(tmp_path / "bad-rule-means", means=123))
    if err:
        problems.append(f"rule non-text means: {err}")
    elif not (
        rule_means_diag.code == "R000"
        and rule_means_diag.where.endswith("/means")
        and rule_means_diag.span is not None
        and rule_means_diag.span[1] == rule_means_line
    ):
        problems.append(f"rule non-text means diagnostic mismatch: {rule_means_diag.doc()}")

    derived_means_diag, err = _single_refusal(lambda: _lower_derived_note(tmp_path / "bad-derived-means", means=123))
    if err:
        problems.append(f"derived non-text means: {err}")
    elif not (
        derived_means_diag.code == "R000"
        and derived_means_diag.where.endswith("/means")
        and derived_means_diag.span is not None
        and derived_means_diag.span[1] == derived_means_line
    ):
        problems.append(f"derived non-text means diagnostic mismatch: {derived_means_diag.doc()}")

    if rule_means_diag is not None and derived_means_diag is not None and rule_means_diag.message != derived_means_diag.message:
        problems.append(
            f"non-text means message diverged between rule ({rule_means_diag.message!r}) "
            f"and derived ({derived_means_diag.message!r})"
        )

    rule_source_diag, err = _single_refusal(lambda: _lower_rule_note(tmp_path / "bad-rule-source", source=123))
    if err:
        problems.append(f"rule non-text source: {err}")
    elif not (
        rule_source_diag.code == "R000"
        and rule_source_diag.where.endswith("/source")
        and rule_source_diag.span is not None
    ):
        problems.append(f"rule non-text source diagnostic mismatch: {rule_source_diag.doc()}")

    derived_source_diag, err = _single_refusal(lambda: _lower_derived_note(tmp_path / "bad-derived-source", source=123))
    if err:
        problems.append(f"derived non-text source: {err}")
    elif not (
        derived_source_diag.code == "R000"
        and derived_source_diag.where.endswith("/source")
        and derived_source_diag.span is not None
    ):
        problems.append(f"derived non-text source diagnostic mismatch: {derived_source_diag.doc()}")

    if rule_source_diag is not None and derived_source_diag is not None and rule_source_diag.message != derived_source_diag.message:
        problems.append(
            f"non-text source message diverged between rule ({rule_source_diag.message!r}) "
            f"and derived ({derived_source_diag.message!r})"
        )

    problems.extend(_native_rule_lowering_duplicates_note_validation())

    assert not problems, "\n".join(problems)
