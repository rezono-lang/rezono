import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read a unit defined as a multiple written with a power (2^30 B) and a unit per a unit (Cents per Hour) "
           "into the member is, as written, in rezono/src/module-unit.ts. Read docs/rezono/v0.md section 5 (Units, "
           "enums and parameters) and decisions/language-units.md. No dependency.",
)
def test_unit_definition():
    assert_reader_case("unit_definition")
