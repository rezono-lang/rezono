import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read the top-level evaluation date, as of DAY known DAY, into asOf and known in a new rezono/src/module-context.ts registered in module-components.ts. Read decisions/language-parameters.md.",
)
def test_time_policy():
    assert_reader_case("time_policy")
