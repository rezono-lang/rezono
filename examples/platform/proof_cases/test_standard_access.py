import pytest

from case_support import engine, imported, verified


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on test_standard_imports. Supply the access case through examples/platform platform bindings in schema, facts, views or rules using a separate access module. Read decisions/platform-derivation-acceptance.md.')
def test_standard_access():
    imported("std-access")
    state = engine()[1]
    grants = state.derived.get("may_read", set())
    assert ("elm", "quota", "elm-quota") in grants and ("elm", "request", "elm-request") in grants
    assert ("elm", "quota", "reed-quota") not in grants and ("elm", "request", "reed-request") not in grants
    leaves = verified("tenant_capacity_fits", ("elm", "elm-request", "elm-quota"))
    evidence = {(kind, identifier) for rel, key in leaves for kind in ("request", "quota")
                for identifier in key if identifier.endswith("-" + kind)}
    assert evidence == {("quota", "elm-quota"), ("request", "elm-request")}
    assert all(("elm", kind, identifier) in grants for kind, identifier in evidence)
