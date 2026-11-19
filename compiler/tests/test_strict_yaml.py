"""A pack file that names the same key twice is refused, never read as its last occurrence.

`yaml.safe_load` keeps the last of two equal keys without a word: a fact file that names a kind twice would lose
the first block. The compiler reads pack files through `rezono_compiler.strict_yaml`, and the scan below keeps it
that way for every `yaml` read under `compiler/rezono_compiler/`.
"""

import ast
import datetime
import shutil
from pathlib import Path

import pytest

from support import FIXTURE
from rezono_compiler import facts, pack, strict_yaml

SOURCE = Path(strict_yaml.__file__).resolve().parent

# The loads that are the strict reader itself: `yaml.load` with the refusing loader of that file.
STRICT = {
    ("strict_yaml.py", "load"): "Loader",
    ("views.py", "read"): "UniqueLoader",
}

# The `yaml` reads that are no pack file, with why each may use a plain loader.
NOT_A_PACK_FILE = {
    ("operate/text.py", "scalar"): "reads back one plain scalar the writer formed, to keep its style",
    ("writer.py", "plain"): "checks that one plain scalar reads back as text under both PyYAML readers",
}

READS = {"load", "safe_load", "full_load", "unsafe_load", "load_all", "safe_load_all", "full_load_all",
         "unsafe_load_all"}


@pytest.fixture(scope="module")
def model():
    return pack.read(FIXTURE)


DUPLICATES = {
    "kind": ("alpha:\n  - {id: a, title: t}\nalpha:\n  - {id: b, title: u}\n", "alpha", 3),
    "field": ("alpha:\n  - id: a\n    title: t\n    title: u\n", "title", 4),
}


@pytest.mark.parametrize("text, key, line", DUPLICATES.values(), ids=DUPLICATES.keys())
def test_a_fact_file_naming_a_key_twice_is_refused(model, tmp_path, text, key, line):
    path = tmp_path / "facts.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(strict_yaml.DuplicateKeyError) as refused:
        facts.load(model, path)
    assert str(refused.value) == f"{path}: duplicate key {key!r} on line {line}"


def test_pack_metadata_naming_a_key_twice_is_refused(tmp_path):
    copy = tmp_path / "minimal"
    shutil.copytree(FIXTURE, copy)
    meta = copy / "pack.yaml"
    meta.write_text(meta.read_text(encoding="utf-8") + 'version: "1"\n', encoding="utf-8")
    with pytest.raises(pack.CompileError, match=r"pack\.yaml: duplicate key 'version' on line \d+"):
        pack.read(copy)


def test_the_strict_reader_keeps_what_safe_load_reads():
    text = "base: &b {x: 1}\nmerged:\n  <<: *b\n  y: 2\nlist: [1, two, 2024-01-02]\n"
    assert strict_yaml.load(text) == {"base": {"x": 1}, "merged": {"x": 1, "y": 2},
                                      "list": [1, "two", datetime.date(2024, 1, 2)]}


def _reads():
    """Every call of a `yaml` reader under the compiler package: (file, enclosing function, loader name, line)."""
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "yaml":
                assert not {a.name for a in node.names} & READS, f"{relative}:{node.lineno}: import the yaml module"
            if isinstance(node, ast.Import):
                assert all(a.asname in (None, "yaml") for a in node.names if a.name == "yaml"), \
                    f"{relative}:{node.lineno}: import yaml under its own name"
        scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in READS
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "yaml"):
                continue
            inside = [s for s in scopes if s.lineno <= node.lineno <= s.end_lineno]
            scope = min(inside, key=lambda s: s.end_lineno - s.lineno).name if inside else "<module>"
            loader = next((k.value for k in node.keywords if k.arg == "Loader"),
                          node.args[1] if len(node.args) > 1 else None)
            name = loader.id if isinstance(loader, ast.Name) else None
            yield relative, scope, node.func.attr, name, node.lineno


def test_every_yaml_read_of_the_compiler_refuses_duplicate_keys():
    found, unexplained = set(), []
    for relative, scope, reader, loader, line in _reads():
        where = (relative, scope)
        found.add(where)
        if where in STRICT:
            if reader != "load" or loader != STRICT[where]:
                unexplained.append(f"{relative}:{line}: {where} must load with {STRICT[where]}")
        elif where not in NOT_A_PACK_FILE:
            unexplained.append(f"{relative}:{line}: yaml.{reader} in {scope}(); read a pack file with "
                               "strict_yaml.read or strict_yaml.load, or list it in NOT_A_PACK_FILE with a reason")
    assert not unexplained, "\n".join(unexplained)
    assert not (set(STRICT) | set(NOT_A_PACK_FILE)) - found, "a listed read is gone; take it off the list"
