"""The usage inventory classifies the schema header that the pack converter writes."""

import pytest

from language_usage import render


class MissingSchemaHeaderClassification(AssertionError):
    """The inventory reported the schema header of a converted module as unclassified syntax."""


MODULE = """rezono 0
pack sample

schema listing
  iri "https://rezono.example/sample/listing"
  language en
  import "linkml:types"
  default range Text
  annotation layer = "facts"

enum State world closed = pending | ready

kind Item world closed
  state: State
"""


@pytest.mark.xfail(
    strict=True,
    raises=MissingSchemaHeaderClassification,
    reason="M3: decisions/language-metadata.md: scripts/language_usage.py classifies the "
           "`schema <name>` header with its indented fields, which scripts/convert_pack.py writes for every "
           "schema with its own identity. It now reports the header as unclassified-authored-syntax, so a "
           "converted pack never counts as converted. The fix lives in scripts/language_usage.py, which the "
           "red guard does not protect, so a fix there can land together with lifting this strict mark.",
)
def test_converted_schema_header_is_not_unclassified_syntax(tmp_path):
    (tmp_path / "packs/sample/rezono").mkdir(parents=True)
    (tmp_path / "packs/sample/pack.yaml").write_text("name: sample\n", encoding="utf-8")
    (tmp_path / "packs/sample/rezono/listing.rezono").write_text(MODULE, encoding="utf-8")
    output = render(tmp_path)
    assert "| kind |" in output and "| enum |" in output
    row = next(line for line in output.splitlines() if line.startswith("| packs/sample |"))
    if "unclassified-authored-syntax" in output:
        raise MissingSchemaHeaderClassification(row)
