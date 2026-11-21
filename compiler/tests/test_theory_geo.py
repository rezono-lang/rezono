"""Theory std-geo, the geometric model of std-space: membership of a point in a region in the four states
(decisions/one-structure-space-and-readings.md, sections 1 and 3, red test 4).

The words this test fixes, as the theory is read by the compiler:
- a kind `grid`, one declared integer grid per reference system;
- a kind `region`, a simple polygon on a grid (`grid`), whose vertices are the kind `vertex` (`region`, `rank`,
  `x`, `y`: integers), taken in the order of `rank`;
- a kind `point` on a grid (`grid`, `x`, `y`: integers);
- a functional derivation `membership(region, point)` over the regions and points of one grid, as rows
  (region, point, state, reason, value): `known` true inside, `known` false outside, and `unknown` with the
  reason `straddles` on the boundary. No separate rough-set or egg-yolk model: the state order of Rezono.
The oracle is an exact even-odd test with integer and fraction arithmetic, written here and sharing no code
with the compiler. A few points are also stated by hand, so that the oracle itself is checked.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from rezono_compiler import pack
from rezono_compiler import rules as ir

pytest.importorskip("duckdb")

REPO = Path(__file__).resolve().parents[2]
THEORY = REPO / "packs" / "std-geo"

# An L, so that a convex shortcut fails in the notch, and a square beside it.
REGIONS = {
    "L": [(0, 0), (4, 0), (4, 2), (2, 2), (2, 4), (0, 4)],
    "Q": [(6, 0), (8, 0), (8, 2), (6, 2)],
}
POINTS = [(x, y) for x in range(-1, 10) for y in range(-1, 6)]
BY_HAND = {
    ("L", 1, 1): "inside", ("L", 3, 1): "inside", ("L", 1, 3): "inside", ("L", 2, 1): "inside",
    ("L", 3, 3): "outside", ("L", 5, 1): "outside", ("L", -1, -1): "outside",
    ("L", 2, 3): "boundary", ("L", 3, 2): "boundary", ("L", 2, 2): "boundary", ("L", 0, 0): "boundary",
    ("L", 4, 1): "boundary", ("L", 1, 4): "boundary",
    ("Q", 7, 1): "inside", ("Q", 6, 1): "boundary", ("Q", 8, 2): "boundary", ("Q", 5, 1): "outside",
}
ROW = {"inside": ("known", "", "true"), "outside": ("known", "", "false"), "boundary": ("unknown", "straddles", "")}


class MissingGeometricModel(AssertionError):
    """packs/std-geo is not yet a theory pack."""


def side(polygon, x, y):
    """inside, outside or boundary: on an edge first, then the even-odd count of crossings to the right."""
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        on_line = (x2 - x1) * (y - y1) == (y2 - y1) * (x - x1)
        if on_line and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return "boundary"
        if (y1 > y) != (y2 > y) and x < x1 + Fraction((y - y1) * (x2 - x1), y2 - y1):
            inside = not inside
    return "inside" if inside else "outside"


def point_id(x, y):
    return f"p{x}_{y}"


def rows():
    vertices = [(f"{r}{i}", r, i, x, y) for r, poly in REGIONS.items() for i, (x, y) in enumerate(poly)]
    return {
        "grid": [("g",)],
        "region": [(r,) for r in REGIONS], "region__grid": [(r, "g") for r in REGIONS],
        "vertex": [(v,) for v, *_ in vertices], "vertex__region": [(v, r) for v, r, *_ in vertices],
        "vertex__rank": [(v, i) for v, _, i, _, _ in vertices],
        "vertex__x": [(v, x) for v, *_, x, _ in vertices], "vertex__y": [(v, y) for v, *_, y in vertices],
        "point": [(point_id(x, y),) for x, y in POINTS], "point__grid": [(point_id(x, y), "g") for x, y in POINTS],
        "point__x": [(point_id(x, y), x) for x, y in POINTS], "point__y": [(point_id(x, y), y) for x, y in POINTS],
    }


def normal(row):
    region, point, state, reason, value = row
    return (str(region), str(point)), (str(state), str(reason or ""), str(value).lower() if state == "known" else "")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 4 (section 3, Spatial uncertainty "
        "uses the four states): waits for compiler/tests/test_theory_space.py--"
        "test_std_space_is_a_fact_free_theory_of_places_parts_and_region_relations. Then add packs/std-geo, the "
        "geometric model, with grid, region, vertex and point on integer coordinates and the functional "
        "derivation membership: known true inside, known false outside, unknown straddles on the boundary."
    ),
)
def test_point_membership_is_known_inside_known_outside_or_unknown_straddles():
    for (region, x, y), want in BY_HAND.items():  # the oracle agrees with the hand
        assert side(REGIONS[region], x, y) == want, (region, x, y)
    if not (THEORY / "pack.yaml").is_file():
        raise MissingGeometricModel(f"{THEORY.relative_to(REPO)} has no pack.yaml")
    theory = pack.read(THEORY)
    assert theory.meta["theory"] is True and not (THEORY / "facts").exists()
    prog = ir.load(theory.rules)

    from rezono_compiler import batch
    con = batch.connect(prog, rows())
    try:
        batch.compute(con, prog)
        got = dict(normal(r) for r in batch.read(con, prog, ["membership"])["membership"])
    finally:
        con.close()
    want = {(r, point_id(x, y)): ROW[side(poly, x, y)] for r, poly in REGIONS.items() for x, y in POINTS}
    assert got == want
