import pytest

from case_support import engine, imported, verified


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Depends on test_standard_imports. Supply the time case through examples/platform platform bindings in schema, facts, views or rules using a separate time module. Read decisions/platform-derivation-acceptance.md.')
def test_standard_time():
    imported("std-time")
    verified("end_not_recorded", ("support",))
    leaves = verified("judgement", ("support", "day-three", "unknown", "end_not_recorded"))
    assert any("support" in k for _, k in leaves)
    assert any("day-three" in k for _, k in leaves)
