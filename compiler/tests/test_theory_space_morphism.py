"""The morphism from the symbolic to the geometric model of space, tested as a theory satisfaction
(decisions/one-structure-space-and-readings.md, section 1 and red test 2).

std-geo binds std-space with a view of its own (`views.yaml`, theory std-space): a region is a place, and a
place is `part_of` the smallest region that contains it on the same grid (closed containment: touching the
boundary from inside is inside). So geometric containment implies part_of, and std-space concludes through the
view what it concludes on that translation. The view maps exactly these two tables of std-space: `place` and
`place__part_of`. The translation below is written by hand from the rectangles, not by the compiler; the
words of std-space and std-geo are those of test_theory_space.py and test_theory_geo.py.

A reversed binding is the failing control: the same view with the path of `part_of` read backwards (its steps
in the other order, each one inverted) gives other rows for place__part_of, and the satisfaction refuses it.
"""

import shutil
from pathlib import Path

import pytest
import satisfaction
import yaml
from rezono_compiler import pack
from rezono_compiler import rules as ir

pytest.importorskip("duckdb")

REPO = Path(__file__).resolve().parents[2]
SPACE = REPO / "packs" / "std-space"
GEO = REPO / "packs" / "std-geo"

# Axis-parallel rectangles on one grid: (x0, y0, x1, y1).
RECTANGLES = {
    "H": (0, 0, 10, 10),   # a hall
    "R": (1, 1, 5, 5),     # a room in it
    "K": (2, 2, 3, 3),     # a rack in the room
    "S": (6, 1, 9, 4),     # a second room
    "T": (0, 0, 2, 1),     # a corner that touches the hall's boundary and the room's edge from outside
}
# The smallest containing rectangle of each, by hand.
PART_OF = {("R", "H"), ("K", "R"), ("S", "H"), ("T", "H")}
WITHIN = PART_OF | {("K", "H")}


class MissingGeometricModel(AssertionError):
    """packs/std-geo is not yet a theory pack that binds std-space by a view."""


def rows(p):
    vertices = []
    for r, (x0, y0, x1, y1) in RECTANGLES.items():
        vertices += [(f"{p}{r}{i}", p + r, i, x, y) for i, (x, y) in enumerate([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])]
    return {
        "grid": [(p + "g",)],
        "region": [(p + r,) for r in RECTANGLES], "region__grid": [(p + r, p + "g") for r in RECTANGLES],
        "vertex": [(v,) for v, *_ in vertices], "vertex__region": [(v, r) for v, r, *_ in vertices],
        "vertex__rank": [(v, i) for v, _, i, _, _ in vertices],
        "vertex__x": [(v, x) for v, *_, x, _ in vertices], "vertex__y": [(v, y) for v, *_, y in vertices],
    }


def translate(p):
    return {"place": {(p + r,) for r in RECTANGLES}, "place__part_of": {(p + a, p + b) for a, b in PART_OF}}


def reversed_path(path):
    return path | {"steps": [step | {"inverse": not step.get("inverse", False)} for step in reversed(path["steps"])]}


def geometric_model(root, reverse=False):
    """std-space and std-geo side by side, as std-geo imports std-space; with `reverse`, std-geo's view reads the
    path of part_of backwards."""
    shutil.copytree(REPO / "packs" / "std-part", root / "std-part")
    shutil.copytree(SPACE, root / "std-space")
    geo = Path(shutil.copytree(GEO, root / "std-geo"))
    if reverse:
        doc = yaml.safe_load((geo / "views.yaml").read_text(encoding="utf-8"))
        [view] = [v for v in doc["views"] if v["theory"] == "std-space"]
        [arrow] = [a for a in view["arrows"] if (a["of"], a["name"]) == ("place", "part_of")]
        arrow["paths"] = [reversed_path(p) for p in arrow["paths"]]
        (geo / "views.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")
    return ir.load(pack.read(geo).rules)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/one-structure-space-and-readings.md: Red tests, 2 (section 1, Space is a theory): "
        "waits for compiler/tests/test_theory_geo.py--"
        "test_point_membership_is_known_inside_known_outside_or_unknown_straddles. Then let packs/std-geo bind "
        "std-space by a view that maps place to region and part_of to the smallest containing region, so that "
        "std-space is satisfied through it and a view with the part_of path reversed is refused."
    ),
)
def test_geometric_containment_satisfies_part_of_and_a_reversed_binding_fails(tmp_path):
    if not (GEO / "views.yaml").is_file() or not (SPACE / "pack.yaml").is_file():
        raise MissingGeometricModel("packs/std-geo binds no std-space by a view of its own")
    prog = geometric_model(tmp_path / "model")
    data = {n: sorted(r) for n, r in rows("i0").items()}
    through = satisfaction.satisfied(prog, data, SPACE, translate("i0"))
    assert through["within"] == {("i0" + a, "i0" + b) for a, b in WITHIN}
    assert not satisfaction.violations(SPACE, through), "the geometry breaks no axiom of std-space"

    control = geometric_model(tmp_path / "reversed", reverse=True)
    with pytest.raises(AssertionError, match="other rows for place__part_of"):
        satisfaction.satisfied(control, data, SPACE, translate("i0"))
