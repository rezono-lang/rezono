import pytest

from case_support import engine, imported, verified


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on test_standard_imports. Supply the order case through examples/platform platform bindings in schema, facts, views or rules using a separate order module. Read decisions/platform-derivation-acceptance.md.')
def test_standard_order():
    imported("std-order")
    expected = {("request", "review"), ("review", "apply"), ("request", "apply")}
    actual = {row for row in engine()[1].derived.get("before", ()) if set(row) <= {"review", "request", "apply"}}
    assert actual == expected
    leaves = verified("before", ("request", "apply"))
    assert {("ordered__precedes", ("request", "review")), ("ordered__precedes", ("review", "apply"))} <= leaves
