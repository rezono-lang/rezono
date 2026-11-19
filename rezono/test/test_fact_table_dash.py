"""A dash omits a slot in a fact table on its own, as it does in a table of a dataset."""

import json

import pytest

from reader_probe import read_modules

HEADER = "rezono 0\npack sample\n"
TABLE = HEADER + "fact Host\n  | id     | owner |\n  | host-a | -     |\n"


class MissingFactTableDash(AssertionError):
    """The reader refused a dash in a slot column of a fact table that stands on its own."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingFactTableDash,
    reason="M3: decisions/language-facts.md: In rezono/src/module-facts.ts, read a dash in a slot column of a fact "
           "table that stands on its own as {boundary: omitted}, as in a table of a dataset, and keep refusing it "
           "in the identity column. Read section A dash in any fact table. Waits for test_structured_fact while it "
           "owns module-facts.ts.",
)
def test_dash_omits_a_slot_in_a_fact_table():
    identity = TABLE.replace("| host-a | -     |", "| -      | -     |")
    read, refused = read_modules(TABLE, identity)
    # The counter-case holds before and after: a row without its identity has no meaning.
    assert refused["module"] is None and [d["code"] for d in refused["diagnostics"]] == ["R000"], refused
    expected = [{"fact": "Host", "columns": ["id", "owner"], "rows": [[{"lit": "host-a"}, {"boundary": "omitted"}]]}]
    if read["diagnostics"] or (read["module"] or {}).get("decls") != expected:
        raise MissingFactTableDash(json.dumps(read, indent=2))
