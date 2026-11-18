import pytest

from case_support import engine, imported, verified


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on test_standard_imports. Supply the identity case through examples/platform platform bindings in schema, facts, views or rules using a separate identity module. Read decisions/platform-derivation-acceptance.md.')
def test_standard_identity():
    imported("std-identity")
    conflicts = {row for row in engine()[1].derived.get("identity_conflict", ()) if set(row[:2]) == {"a", "b"}}
    assert conflicts == {("a", "b", "edition"), ("b", "a", "edition")}
    leaves = verified("identity_conflict", ("a", "b", "edition"))
    assert any(k == ("a", "b") or k == ("b", "a") for _, k in leaves)
    assert sum("edition" in k for _, k in leaves) >= 2
