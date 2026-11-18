"""Link independent native rule trees against a pinned schema closure."""

from copy import deepcopy
from importlib.util import find_spec

import pytest
import yaml

from rezono_compiler import modules, pack


ROOT = ("journey", "rezono/tracks.rezono")
OWNER = ("route-map", "rezono/catalog.rezono")


def _form(name, decls, uses=()):
    """Supply positions for this in-memory tree without a Rezono reader."""
    body = {"rezono": "0", "pack": name, "use": list(uses), "decls": decls}
    places = []
    for section in ("decls", "use"):
        for index, node in enumerate(body[section]):
            line = index + (3 if section == "use" else 3 + len(uses))
            for pointer in _pointers(node, f"/{section}/{index}"):
                start = str(100 * line)
                places.append({"at": pointer, "line": str(line), "start": start, "end": start})
    return {"format": "rezono.module/3", "module": body, "spans": places}


def _pointers(value, at):
    if isinstance(value, dict):
        yield at
        for name, child in sorted(value.items()):
            yield from _pointers(child, f"{at}/{name}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _pointers(child, f"{at}/{index}")


def _path(*segments):
    return {"path": list(segments)}


def _call(name, *variables):
    return {"call": [name, [_path(variable) for variable in variables]]}


def _column(name, kind):
    return {"name": name, "type": kind}


def _write_yaml(filename, value):
    filename.write_text(yaml.safe_dump(value), encoding="utf-8")


def _fixture(tmp_path):
    owner, consumer = tmp_path / OWNER[0], tmp_path / ROOT[0]
    (owner / "schema").mkdir(parents=True)
    consumer.mkdir()
    _write_yaml(owner / "pack.yaml", {"name": OWNER[0], "version": "1", "default_language": "en"})
    # TimedStop inherits an integer key and a reference slot. Counter has the
    # same key representation and slot shape but is nominally unrelated.
    code = {"identifier": True, "range": "integer"}
    next_stop = {"range": "TimedStop", "required": True}
    schema = owner / "schema/stops.yaml"
    _write_yaml(schema, {
        "id": "https://example.org/route-map", "name": "stops", "imports": ["linkml:types"],
        "annotations": {"layer": "facts"},
        "classes": {
            "Stop": {"attributes": {"code": code, "next": next_stop}},
            "TimedStop": {"is_a": "Stop"},
            "Counter": {"attributes": {"code": dict(code), "next": dict(next_stop)}},
        },
    })
    _write_yaml(consumer / "pack.yaml", {
        "name": ROOT[0], "version": "1", "default_language": "en",
        "imports": [{"name": OWNER[0], "path": f"../{owner.name}", "sha256": modules.pack_hash(owner)}],
    })
    return consumer, schema


def _forms():
    owner = [
        {"rule": "flagged", "columns": [_column("item", "TimedStop")], "options": [{"extend": True}]},
        {"rule": "sealed", "columns": [_column("item", "TimedStop")],
         "when": {"in": [_path("item"), {"kind": "TimedStop"}]}},
    ]
    pair = [_column("start", "map.TimedStop"), _column("end", "map.TimedStop")]
    consumer = [
        {"rule": "reachable", "args": [_path("x"), _path("y")], "locals": [_column("mid", "map.TimedStop")],
         "when": {"and": [_call("reachable", "x", "mid"), {"cmp": ["=", _path("mid", "next"), _path("y")]}]}},
        {"rule": "reachable", "columns": pair, "when": _call("one_step", "start", "end")},
        {"rule": "one_step", "columns": pair,
         "when": {"cmp": ["=", _path("start", "next"), _path("end")]}},
        {"rule": "stop_code", "columns": [_column("item", "map.TimedStop"), _column("code", "Int")],
         "when": {"and": [_call("reachable", "item", "item"),
                          {"cmp": ["=", _path("item", "code"), _path("code")]}]}},
        {"rule": "map.flagged", "args": [_path("x")], "when": _call("map.sealed", "x")},
    ]
    return {
        ROOT: _form(ROOT[0], consumer, [{"use": OWNER[0], "as": "map"}]),
        OWNER: _form(OWNER[0], owner),
    }


def _diagnostics(link, directory, forms, code):
    with pytest.raises(pack.CompileError) as error:
        link(directory, forms)
    found = {(d.span[0], d.span[1]) for d in error.value.diagnostics if d.code == code and d.span}
    assert found, error.value.diagnostics
    return found


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/language-native-rules.md (PR #431). Implement compiler/rezono_compiler/"
        "native_rule_signatures.py. Link authored module/3 trees against the pinned schema closure. "
        "No parser, form reader, pack integration or rule lowering prerequisite."
    ),
)
def test_native_rule_signatures(tmp_path):
    """link(pack_dir, forms) accepts forms keyed by (pack name, relative Rezono source path).

    Inspect signatures by resolved relation, and clauses by (pack, source path,
    declaration pointer). Resolve calls and paths by the pointer of the expression.
    The key triples retain the column name, semantic type and rule storage type.
    """
    directory, schema = _fixture(tmp_path)
    forms = _forms()
    assert find_spec("rezono_compiler.native_rule_signatures") is not None, "Native rule signature linker is missing"
    from rezono_compiler.native_rule_signatures import link

    linked = link(directory, forms)
    assert linked.signatures["reachable"].key == (
        ("start", "timed_stop", "integer"), ("end", "timed_stop", "integer"),
    )
    assert linked.signatures["stop_code"].key == (("item", "timed_stop", "integer"), ("code", "Int", "integer"))
    assert linked.signatures["flagged"].key == (("item", "timed_stop", "integer"),)
    assert linked.signatures["flagged"].module == "import_route_map_catalog"

    recursive = linked.clauses[(*ROOT, "/decls/0")]
    assert recursive.relation == "reachable"
    assert recursive.calls["/decls/0/when/and/0"] == "reachable"
    assert recursive.paths["/decls/0/when/and/1/cmp/1"] == ("stop__next", "timed_stop")
    assert linked.clauses[(*ROOT, "/decls/1")].calls["/decls/1/when"] == "one_step"
    # The inherited code projects the key already bound for the row, with no slot read.
    assert linked.clauses[(*ROOT, "/decls/3")].paths["/decls/3/when/and/1/cmp/1"] == (None, "Int")

    extension = linked.clauses[(*ROOT, "/decls/4")]
    assert extension.relation == "flagged" and extension.module == "import_route_map_catalog"
    assert extension.calls["/decls/4/when"] == "sealed"

    wrong_kind = deepcopy(forms)
    wrong_kind[ROOT]["module"]["decls"][0]["locals"][0]["type"] = "map.Counter"
    assert (ROOT[1], 4) in _diagnostics(link, directory, wrong_kind, "R003")

    closed = deepcopy(forms)
    closed[ROOT]["module"]["decls"][4]["rule"] = "map.sealed"
    assert (ROOT[1], 8) in _diagnostics(link, directory, closed, "R046")

    duplicate = deepcopy(forms)
    amended = duplicate[ROOT]["module"]
    amended["decls"].append({
        "rule": "flagged", "columns": [_column("item", "map.TimedStop")],
        "when": _call("map.sealed", "item"),
    })
    duplicate[ROOT] = _form(ROOT[0], amended["decls"], amended["use"])
    assert _diagnostics(link, directory, duplicate, "R040") >= {
        (ROOT[1], 9), (f"{OWNER[0]}:{OWNER[1]}", 3),
    }

    # Change only definition bytes. The old name, schema semantics and use alias still match.
    schema.write_bytes(schema.read_bytes() + b"\n# changed after the import was pinned\n")
    assert (ROOT[1], 3) in _diagnostics(link, directory, forms, "R046")
