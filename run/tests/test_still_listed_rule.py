"""A delivered service still listed is a cleanup row: decisions/code-does-not-decide.md.

The expectation is the behaviour of run/ovh_inventory.py under decisions/run-price-enforcement.md, "Cleanup":
the run is clean when no service delivered by the plan's orders appears in a fresh unfiltered list.
"""
import pytest

from offline_cases import implementation

DELIVERED = ["srv-2.example.org", "srv-1.example.org"]


def pack_reads(monkeypatch):
    """The (pack, relation) pairs whose derived rows the code reads."""
    from rezono_compiler import batch

    seen = set()
    read = batch.read

    def spy(con, prog, names=None):
        rows = read(con, prog, names)
        seen.update((prog.pack, name) for name in rows)
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return seen


def test_still_listed_services_come_from_the_cleanup_pack(monkeypatch):
    seen = pack_reads(monkeypatch)
    remaining = implementation("ovh_inventory.py", "remaining")
    assert remaining(b'["other.example.org", "srv-1.example.org"]', DELIVERED) == ["srv-1.example.org"]
    assert remaining(b'["srv-2.example.org", "srv-1.example.org"]', DELIVERED) == DELIVERED[::-1]
    assert remaining(b'["other.example.org"]', DELIVERED) == []
    assert ("cleanup", "still_listed") in seen, sorted(seen)
