"""How many packs the language can take over: the pack table that language_usage.py prints
(decisions/language-first-packs.md)."""

import pytest

from language_usage import render


def first_conversion():
    """Each pack or source directory of the table with its "Mixed conversion" status."""
    lines = render().splitlines()
    start = lines.index("| Pack or source directory | Direct features | Imported features | Pending features "
                        "| Mixed conversion | Native conversion |")
    table = {}
    for line in lines[start + 2:]:
        if not line.startswith("| "):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        table[cells[0]] = cells[4]
    return table


def test_the_pack_table_names_the_first_conversion():
    table = first_conversion()
    assert {"packs/std-access", "run/packs/exact-quote", "examples/library"} <= set(table)
    assert all(status in {"Ready", "No owning pack", "No language sources"} or status.startswith("Pending: ")
               for status in table.values()), table


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M3: decisions/language-first-packs.md: At least 15 packs of examples/, packs/ and run/packs/ are Ready "
    "for the first conversion in the table of compiler/tests/rezono/language_usage.py. No code of its own: "
    "waits for test_lower_schema_annotations and test_lower_open_world, and the task that makes the last of "
    "them pass removes this mark too. If they pass and fewer than 15 packs are Ready, record here which "
    "building blocks still hold them back."))
def test_fifteen_packs_are_ready_for_the_first_conversion():
    ready = sorted(name for name, status in first_conversion().items() if status == "Ready")
    assert len(ready) >= 15, ready
