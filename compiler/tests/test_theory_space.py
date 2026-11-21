"""Theory std-space: places, their parts and the region relations, without facts
(decisions/one-structure-space-and-readings.md, section 1 and red test 1).

The words this test fixes, as the theory is read by the compiler:
- a kind `place`, whose single-valued `part_of` is std-part's: std-space imports std-part, so std-part's
  `within` and `outermost` hold over places;
- an enum `region_relation` with the eight relations of region connection, spelled out as std-time spells
  Allen's relations;
- a kind `connection` that states one relation between two places (`first`, `second`, `relation`);
- an invariant `region_conflict(x, y)`: what holds between x and y cannot all be true. Two different
  relations hold for (x, y); or x lies within y and a relation other than a proper part holds for (x, y); or
  y lies within x and a relation other than an inverse proper part holds for (x, y). A stated relation also
  holds in its converse for (y, x).
Every expectation below is worked out by hand from these definitions.
"""

from pathlib import Path

import pytest
from rezono_compiler import pack
from rezono_compiler import rules as ir

pytest.importorskip("duckdb")

REPO = Path(__file__).resolve().parents[2]
THEORY = REPO / "packs" / "std-space"

REGION_RELATIONS = {
    "disconnected", "externally_connected", "partially_overlapping", "equal",
    "tangential_proper_part", "non_tangential_proper_part",
    "tangential_proper_part_inverse", "non_tangential_proper_part_inverse",
}


class MissingSpaceTheory(AssertionError):
    """packs/std-space is not yet a theory pack."""


def run(prog, data):
    from rezono_compiler import batch
    con = batch.connect(prog, data)
    try:
        batch.compute(con, prog)
        return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in batch.read(con, prog).items()}
    finally:
        con.close()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 1 (section 1, Space is a theory): "
        "add packs/std-space as a theory pack "
        "without facts that imports std-part for part_of, declares the kind place, the enum region_relation "
        "with the eight relations of region connection, the kind connection and the invariant region_conflict."
    ),
)
def test_std_space_is_a_fact_free_theory_of_places_parts_and_region_relations():
    if not (THEORY / "pack.yaml").is_file():
        raise MissingSpaceTheory(f"{THEORY.relative_to(REPO)} has no pack.yaml")
    theory = pack.read(THEORY)
    assert theory.meta["theory"] is True, "std-space is a theory: neutral words, axioms and rules"
    assert not (THEORY / "facts").exists(), "a theory has no facts of its own"
    assert {"place", "connection"} <= set(theory.kinds)
    assert set(theory.enums.get("region_relation", ())) == REGION_RELATIONS

    prog = ir.load(theory.rules)
    data = {
        "place": [("a",), ("b",), ("c",), ("d",)],
        "place__part_of": [("a", "b"), ("b", "c")],
        "connection": [("k1",), ("k2",), ("k3",), ("k4",)],
        "connection__first": [("k1", "a"), ("k2", "b"), ("k3", "c"), ("k4", "d")],
        "connection__second": [("k1", "b"), ("k2", "c"), ("k3", "d"), ("k4", "c")],
        "connection__relation": [("k1", "externally_connected"), ("k2", "tangential_proper_part"),
                                 ("k3", "disconnected"), ("k4", "partially_overlapping")],
    }
    got = run(prog, data)

    # part_of is std-part's: its conclusions hold over places.
    assert got["within"] == {("a", "b"), ("b", "c"), ("a", "c")}
    assert got["outermost"] == {("a", "c"), ("b", "c")}

    # The region relations as axioms. k1: a lies within b, but externally_connected is no proper part, and its
    # converse (b, a) is no inverse proper part. k2: tangential_proper_part fits b within c, both ways. k3 and k4:
    # disconnected is its own converse, so (d, c) holds both disconnected and partially_overlapping.
    assert prog.relations["region_conflict"].invariant
    assert got["region_conflict"] == {("a", "b"), ("b", "a"), ("c", "d"), ("d", "c")}
