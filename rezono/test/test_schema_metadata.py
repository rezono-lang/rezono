import pytest

from reader_case import assert_reader_case


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Read schema metadata into the module/2 form in rezono/src. Read decisions/language-metadata.md. Waits for the reader split in PR #429 (shared reader and printer).",
)
def test_schema_metadata():
    assert_reader_case("schema_metadata")
