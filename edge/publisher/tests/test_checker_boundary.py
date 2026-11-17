"""The filter and the check on it share no code.

The publisher's filter decides what a role gets (rezono_publisher.access); the checker derives the same on its
own and compares (rezono_checker.access). That is a check only while the two do not read the question through the
same functions. So the filter modules import nothing of the checker but its `check_*` entry points, no module of
the publisher imports the checker's reading of the calculation program (rezono_checker.calc), and the publisher's
own reading (rezono_publisher.calc_scope) agrees with the checker's on every calculation program in the repository.
"""

import ast
import json
from pathlib import Path

import pytest

from rezono_checker import calc as checker_calc
from rezono_publisher import calc_scope

ROOT = Path(__file__).resolve().parents[3]
PUBLISHER = ROOT / "edge" / "publisher" / "rezono_publisher"
# The modules that decide what a role gets: its rows and proofs, what it reads in full, its calculated rows and
# the sources of its rows.
FILTER = ("access.py", "calc_scope.py", "sources.py")


def checker_imports(source: str) -> set[str]:
    """Every name a module takes from the checker, wherever in the module: `rezono_checker.calc.reads` for a name,
    `rezono_checker.calc` for a module."""
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "rezono_checker":
            out |= {f"{node.module}.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name.split(".")[0] == "rezono_checker"}
    return out


@pytest.mark.parametrize("name", FILTER)
def test_a_filter_module_takes_only_check_entry_points_from_the_checker(name):
    assert (PUBLISHER / name).is_file()
    taken = checker_imports((PUBLISHER / name).read_text(encoding="utf-8"))
    assert {n for n in taken if not n.rsplit(".", 1)[-1].startswith("check_")} == set()


def test_no_publisher_module_reads_the_calculation_program_through_the_checker():
    """`published_views`, `subject_of`, `reads` and `version_of` are how the checker decides what a role sees of
    a calculation. A publisher that calls them asks the checker what to publish, and the check then agrees."""
    using = {p.name: sorted(n for n in checker_imports(p.read_text(encoding="utf-8")) if n.startswith("rezono_checker.calc"))
             for p in sorted(PUBLISHER.glob("*.py"))}
    assert {name: names for name, names in using.items() if names} == {}


def test_the_scan_sees_every_way_to_import():
    source = ("import json\nfrom rezono_checker import calc\nimport rezono_checker.access as a\n"
              "def f():\n    from rezono_checker.calc import reads as r\n    from rezono_canon import canonical_json\n")
    assert checker_imports(source) == {"rezono_checker.calc", "rezono_checker.access", "rezono_checker.calc.reads"}


# Every calculation program in the repository: the compiled goldens of the example packs, the contract fixtures
# and the example the checker's own tests are frozen on.
PROGRAMS = sorted(p for base in ("examples", "contracts/fixtures", "checker/tests/fixtures", "compiler/tests/fixtures")
                  for p in (ROOT / base).rglob("calc.json") if p.parent.name != "engine")


def program(path: Path) -> dict | None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) and doc.get("format") == "rezono.calc-ir/1" else None


@pytest.mark.xfail(strict=True, reason="generated expected/compiled calc.json goldens are not stored in git")
def test_there_are_programs_to_compare():
    assert sum(program(p) is not None for p in PROGRAMS) >= 3


@pytest.mark.parametrize("path", PROGRAMS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_both_readings_agree_on_a_calculation_program(path):
    ir = program(path)
    if ir is None:
        pytest.skip("not a calculation IR")
    assert calc_scope.published_views(ir) == checker_calc.published_views(ir)
    for version in [None, *(v["id"] for v in ir.get("versions", ()))]:
        assert calc_scope.reads(ir, version) == checker_calc.reads(ir, version), version
    # What each view rests on: the same sources, and each view accounted for by the same reading.
    assert calc_scope.view_sources(ir) == checker_calc.sources(ir)
    # A witness of each kind of view: of a rule with a chosen version, of a rule without one, of a version itself.
    witnesses = [{"conclusion": {"relation": r["view"]}, "rule": r["rule"], "version": v.partition("@")[2]}
                 for r in ir.get("rules", ()) for v in (*r.get("versions", ()), "")]
    witnesses += [{"conclusion": {"relation": v["view"]}, "rule": v["id"].partition("@")[0]} for v in ir.get("versions", ())]
    assert witnesses
    for w in witnesses:
        assert calc_scope.version_of(ir, w) == checker_calc.version_of(ir, w), w


def test_both_readings_agree_on_the_frozen_witnesses():
    fixture = ROOT / "checker" / "tests" / "fixtures" / "calc"
    ir = json.loads((fixture / "calc.json").read_text(encoding="utf-8"))
    witnesses = json.loads((fixture / "witnesses.json").read_text(encoding="utf-8"))
    assert witnesses
    for w in witnesses:
        version = calc_scope.version_of(ir, w)
        assert version == checker_calc.version_of(ir, w)
        assert calc_scope.reads(ir, version) == checker_calc.reads(ir, version) == set(w["reads"])
        assert calc_scope.subject_of(w["conclusion"]["key"]) == checker_calc.subject_of(w["conclusion"]["key"]) is not None


@pytest.mark.parametrize("key", ['["s","1","known",""]', '["s","","unknown","fact x is missing"]', '["s","1","known"]',
                                 '["s",1,"known",""]', '{"subject":"s"}', "[", "", None, '"s"', '[["s"],"1","known",""]'])
def test_both_readings_agree_on_what_a_subject_is(key):
    assert calc_scope.subject_of(key) == checker_calc.subject_of(key)
