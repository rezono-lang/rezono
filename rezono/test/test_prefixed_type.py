import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read a slot type with a pack prefix (terms.Party) into the slot member type, as written, in "
           "rezono/src/module-slot.ts, and widen TypeText in contracts/rezono-module.yaml by one optional prefix. Read "
           "decisions/language-imports.md, section Reading a prefixed type. No dependency.",
)
def test_prefixed_type():
    assert_reader_case("prefixed_type")
