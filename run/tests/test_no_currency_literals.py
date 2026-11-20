"""No run or loop module names a currency: decisions/code-does-not-decide.md, section 3, and AGENTS.md rule 1."""
import ast

import pytest

from offline_cases import RUN

# ISO 4217 codes a run could meet; the list is the test's own, independent of any pack.
CURRENCIES = {"AUD", "CAD", "CHF", "CNY", "CZK", "DKK", "EUR", "GBP", "INR", "JPY", "NOK", "PLN", "SEK", "USD"}


def currency_literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted({(node.lineno, node.value) for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and node.value in CURRENCIES})


def test_no_module_names_a_currency():
    modules = sorted([*RUN.glob("*.py"), *(RUN.parent / "loop").glob("*.py")])
    assert modules
    found = {path.relative_to(RUN.parent).as_posix(): currency_literals(path) for path in modules}
    assert {name: lines for name, lines in found.items() if lines} == {}
