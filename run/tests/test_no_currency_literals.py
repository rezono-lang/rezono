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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/code-does-not-decide.md, currency row and section 3. The currency of a capture, the pair "
        "of a rate capture and the currency of a price publication are facts of run/packs/exact-quote, next to "
        "the CurrencyCode enums of run/packs/dispatch and run/packs/invoice-drift; code passes the recorded "
        "strings through and compares them with no literal. Today run/closed_month.py:99, "
        "run/effective_quote.py:83 and :125 and run/order_day_review.py:121, :136 and :162 name USD or EUR. "
        "Keep run/tests/test_closed_month.py, test_effective_currency.py and test_order_day_review.py green "
        "(AssertionError)."
    ),
)
def test_no_module_names_a_currency():
    modules = sorted([*RUN.glob("*.py"), *(RUN.parent / "loop").glob("*.py")])
    assert modules
    found = {path.relative_to(RUN.parent).as_posix(): currency_literals(path) for path in modules}
    assert {name: lines for name, lines in found.items() if lines} == {}
