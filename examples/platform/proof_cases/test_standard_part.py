import pytest

from case_support import engine, imported, verified


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on test_standard_imports. Supply the part case through examples/platform platform bindings in schema, facts, views or rules using a separate part module. Read decisions/platform-derivation-acceptance.md.')
def test_standard_part():
    imported("std-part")
    verified("within", ("database", "catalog-entry"))
    leaves = verified("outermost", ("database", "catalog-entry"))
    assert {("constituent__part_of", ("database", "delivery")), ("constituent__part_of", ("delivery", "catalog-entry"))} <= leaves
