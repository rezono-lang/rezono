"""RV-K03: the checker stands on its own. It imports the standard library, PyYAML and rezono_canon, and nothing of
the compiler, the publisher or the engine: what it checks, it cannot have asked them.
(The other side of the boundary, that the publisher's filter does not read through the checker, is held in
edge/publisher/tests/test_checker_boundary.py.)"""

import ast
import sys
from pathlib import Path

import rezono_checker

ALLOWED = set(sys.stdlib_module_names) | {"yaml", "rezono_canon", "rezono_checker"}


def imported(source: str) -> set[str]:
    """The top-level package of every absolute import, wherever in the module."""
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            out.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
    return out


def test_the_checker_imports_only_the_standard_library_yaml_and_canon():
    modules = sorted(Path(rezono_checker.__file__).parent.rglob("*.py"))
    assert modules
    outside = {m.name: sorted(imported(m.read_text(encoding="utf-8")) - ALLOWED) for m in modules}
    assert {name: names for name, names in outside.items() if names} == {}


def test_the_scan_sees_every_way_to_import():
    source = ("import json, duckdb\nfrom . import canon\nfrom .rules import load_rules\nfrom rezono_canon import canonical_json\n"
              "def f():\n    from rezono_compiler.rules import INT\n    import rezono_publisher.access as a\n")
    assert imported(source) - ALLOWED == {"duckdb", "rezono_compiler", "rezono_publisher"}
