"""Every compiler error has a code (decisions/compiler-error-codes.md): an IRError keeps its own code in the
diagnostic list, and the error sites without a code stay at or below a budget that only goes down."""

import ast
import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from support import FIXTURE, REPO
from rezono_compiler import pack

SOURCE = REPO / "compiler" / "rezono_compiler"
BUDGET = REPO / "compiler" / "error-code-budget.json"
CEILING = 869  # the total when the budget was set; a lower budget replaces it, a higher one is a new decision
# Each cell (file, class) may not rise above the same cell on the base: scripts/test_error_code_budget.py in CI.
COUNTED = ("CompileError", "LoadError", "OperationError", "WriteError", "RuleError", "ViewError", "ViewRuleError",
           "PatternError", "IdentityError", "Unmatched")
FORWARDS = {"CompileError", "LoadError"}  # Diagnosed(message, diagnostics): a second argument forwards diagnostics
COLLECTED = "collected"  # errors.append(<a sentence>), joined into one CompileError


def _name(node) -> str | None:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def uncoded(text: str) -> Counter:
    """The error sites in one module's text that give no code, per class (and `collected`)."""
    found: Counter = Counter()
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        if name in COUNTED:
            keywords = {k.arg for k in node.keywords}
            if not keywords & {"code", "diagnostics"} and not (name in FORWARDS and len(node.args) >= 2):
                found[name] += 1
        elif (name == "append" and isinstance(node.func, ast.Attribute) and _name(node.func.value) == "errors"
              and isinstance(node.func.value, ast.Name)
              and not (node.args and isinstance(node.args[0], ast.Call) and _name(node.args[0].func) == "Diagnostic")):
            found[COLLECTED] += 1
    return found


def counts() -> dict[str, dict[str, int]]:
    out = {}
    for path in sorted(SOURCE.rglob("*.py")):
        found = uncoded(path.read_text("utf-8"))
        if found:
            out[path.relative_to(REPO).as_posix()] = dict(sorted(found.items()))
    return out


def per_class(table: dict[str, dict[str, int]]) -> Counter:
    total: Counter = Counter()
    for found in table.values():
        total.update(found)
    return total


def test_the_count_sees_each_form():
    """The budget can fail: each way of raising without a code counts, each way with one does not."""
    text = "\n".join([
        'raise CompileError("x")', 'raise CompileError("x", code="unknown_kind")', 'raise CompileError("x", found)',
        'raise facts.LoadError(f"{p}: x")', 'raise WriteError("x", code="bad_value")', 'e = OperationError("x")',
        'errors.append(f"{where}: x")', 'errors.append(Diagnostic("unknown_kind", "x"))', 'warnings.append("x")',
        'raise IRError("bad_term", "x")'])
    assert uncoded(text) == Counter({"CompileError": 1, "LoadError": 1, "OperationError": 1, COLLECTED: 1})


def test_error_sites_without_a_code_stay_within_the_budget():
    """A new site without a code is red. Each cell (file x class) stays at or below the budget, so a pull request
    that gives sites a code is green without touching the budget file, and so are two such changes merged together."""
    budget = json.loads(BUDGET.read_text("utf-8"))
    over = {(path, name): (n, budget.get(path, {}).get(name, 0))
            for path, found in counts().items() for name, n in found.items()
            if n > budget.get(path, {}).get(name, 0)}
    assert not over, f"error sites without a code above the budget (found, budget): {over}"
    assert sum(per_class(budget).values()) <= CEILING


def _rule_error(tmp_path: Path, text: str) -> pack.CompileError:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (d / "rules").mkdir()
    (d / "rules" / "core.dl").write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(pack.CompileError) as caught:
        pack.read(d)
    return caught.value


# Two rule programs the rule IR refuses, each with the IRError code that names why (rezono_compiler.rules).
REFUSED = {
    "not_stratified": ".decl p(a: symbol)\n.decl q(a: symbol)\np(a) :- alpha(a), !q(a).\nq(a) :- alpha(a), !p(a).\n",
    "unsafe_variable": ".decl p(a: symbol, b: symbol)\np(a, b) :- alpha(a).\n",
}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/compiler-error-codes.md: Keep the code of an IRError in the diagnostic list: where "
        "rezono_compiler.rules_dl raises an IRError again as RuleError (and view_rules as ViewRuleError), make "
        "the error Diagnosed with one Diagnostic whose code is the IRError's code and whose message is today's "
        "sentence, and let pack.read keep those diagnostics as it keeps view typing's. Today the list says "
        "compile_error."
    ),
)
def test_an_ir_error_keeps_its_code_in_the_diagnostics(tmp_path):
    for n, (code, text) in enumerate(sorted(REFUSED.items())):
        error = _rule_error(tmp_path / str(n), text)
        assert code in str(error), str(error)  # the sentence a reader sees stays as it was
        assert [d.code for d in error.diagnostics] == [code], [d.doc() for d in error.diagnostics]


def _no_sites_left(name: str) -> None:
    left = {path: found[name] for path, found in counts().items() if name in found}
    assert left == {}, f"{name} without a code: {left}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/compiler-error-codes.md: Give every CompileError under compiler/rezono_compiler/ a "
        "code: Diagnosed takes the keyword code and gives each line of its message that code; each site passes "
        "a snake_case code that names what is wrong. Lower compiler/error-code-budget.json with the sites."
    ),
)
def test_every_compile_error_has_a_code():
    _no_sites_left("CompileError")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/compiler-error-codes.md: Waits for compiler/tests/test_error_codes.py--"
        "test_every_compile_error_has_a_code (the keyword code on Diagnosed). Then give every LoadError under "
        "compiler/rezono_compiler/ a code, and lower compiler/error-code-budget.json with the sites."
    ),
)
def test_every_load_error_has_a_code():
    _no_sites_left("LoadError")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/compiler-error-codes.md: Waits for compiler/tests/test_error_codes.py--"
        "test_every_load_error_has_a_code (both lower the same budget). Then make WriteError Diagnosed, "
        "give every WriteError under compiler/rezono_compiler/ a code, and lower compiler/error-code-budget.json "
        "with the sites."
    ),
)
def test_every_write_error_has_a_code():
    _no_sites_left("WriteError")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/compiler-error-codes.md: Waits for compiler/tests/test_error_codes.py--"
        "test_every_write_error_has_a_code (both lower the same budget). Then make OperationError "
        "Diagnosed, give every OperationError under compiler/rezono_compiler/ a code, and lower "
        "compiler/error-code-budget.json with the sites."
    ),
)
def test_every_operation_error_has_a_code():
    _no_sites_left("OperationError")
