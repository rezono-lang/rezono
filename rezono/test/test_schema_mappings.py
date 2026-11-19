import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read close mapping and broad mapping lines into closeMappings and broadMappings in rezono/src/module-metadata.ts, and admit them in the module/2 contract. Read decisions/language-metadata.md, section Close and broad mappings.",
)
def test_schema_mappings():
    assert_reader_case("schema_mappings")
