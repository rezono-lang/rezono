"""S25 step 6a through the real route: the compiler's sources, the batch epoch, the publisher and the checker.

The pack is the compiler's neutral one (compiler/tests/fixtures/minimal) with facts, read rules and a source
sidecar added in a temp dir; it describes no domain. The viewer reads an alpha only when its title is
"open", and every beta.
"""

import dataclasses
import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_canon import canonical_json, sha256_hex  # noqa: E402
from rezono_publisher import batch, publish, store, views  # noqa: E402
from rezono_publisher import sources as fact_sources  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
ROLES = {"checker": "complete", "viewer": "may_read"}
RULES = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "alpha", x) :- alpha__title(x, "open").
may_read("viewer", "beta", x) :- beta(x).
"""
# s1 is an alpha the viewer does not read and also a beta it does: one text id, two kinds.
ALPHAS = "alpha:\n  - {id: a1, title: open, size: 3, flag: true}\n  - {id: s1, title: closed, size: 5, flag: false}\n"
BETAS = "beta:\n  - {id: b1, alpha: a1, state: low}\n  - {id: s1, alpha: a1, state: high}\n"
GIT = {"kind": "git", "name": "example/register", "revision": "0123abc", "position": "rows.json#/0"}


GAMMA = "  Gamma:\n    attributes:\n      id:\n        identifier: true\n        range: integer\n"


def flag(text: str) -> str:
    """A boolean slot on alpha, so a key holds a boolean; and a kind with integer ids no read rule names."""
    return text.replace("      size:\n", "      flag:\n        range: boolean\n      size:\n", 1) + GAMMA


def pack(tmp: Path, sidecar: dict | None = None, alphas: str = ALPHAS, gammas: str = "") -> Path:
    d = tmp / "pack"
    shutil.copytree(MINIMAL, d)
    (d / "facts").mkdir()
    (d / "facts" / "a.yaml").write_text(alphas, encoding="utf-8")
    (d / "facts" / "b.yaml").write_text(BETAS, encoding="utf-8")
    if gammas:
        (d / "facts" / "c.yaml").write_text(gammas, encoding="utf-8")
    if sidecar is not None:
        (d / "facts" / "b.sources.yaml").write_text(yaml.safe_dump(sidecar, sort_keys=True), encoding="utf-8")
    (d / "rules").mkdir()
    (d / "rules" / "access.dl").write_text(RULES, encoding="utf-8")
    p = d / "schema" / "minimal.yaml"
    p.write_text(flag(p.read_text(encoding="utf-8")), encoding="utf-8")
    return d


def epoch(d: Path) -> publish.Epoch:
    return batch.epoch(d, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])


def published(tmp: Path, e: publish.Epoch, base=None):
    s = store.FileStore(tmp / "store")
    return s, publish.publish(e, s, ROLES, base)


def get(s, uri: str) -> bytes:
    return s.get(uri.split("/", 3)[3])  # s3://<bucket>/<key>


def fact_rows(s, m: dict, role: str) -> set:
    """The (relation, key) of every row of a kind or slot table in the role's published snapshots."""
    bundle = json.loads(get(s, next(c["uri"] for c in m["compiled"] if c["file"] == "bundle/schema-bundle.json")))
    tables = {k["table"] for k in bundle["kinds"]} | {a["table"] for p in ("arrows", "attributes") for a in bundle[p]}
    return {(x["relation"], canonical_json(r["key"])) for x in m["snapshots"] if x["role"] == role and x["relation"] in tables
            for r in json.loads(get(s, x["uri"]))}


def role_sources(s, m: dict, role: str) -> list:
    [ref] = [x for x in m["fact_sources"] if x["role"] == role]
    data = get(s, ref["uri"])
    assert sha256_hex(data) == ref["sha256"]
    return json.loads(data)


def test_each_role_gets_the_sources_of_exactly_the_rows_it_reads(tmp_path):
    s, m = published(tmp_path, epoch(pack(tmp_path)))
    assert {"name": "rezono:sources", "status": "green", "violations": 0} in m["checks"]
    assert [x["role"] for x in m["fact_sources"]] == ["checker", "viewer"]
    assert m["sources"] == [{"source_id": "rules", "position": "test"}], "where each source stood, unchanged"
    for role in ROLES:
        entries = role_sources(s, m, role)
        assert {(x["row"]["relation"], x["row"]["key"]) for x in entries} == fact_rows(s, m, role)
        assert entries == sorted(entries, key=lambda x: (x["row"]["relation"].encode("utf-16-be"), x["row"]["key"].encode("utf-16-be")))
    viewer = {(x["row"]["relation"], x["row"]["key"]): x["sources"] for x in role_sources(s, m, "viewer")}
    # The row's own fact file and line: a1 on line 2 of a.yaml, its boolean as the snapshot's text.
    assert viewer[("alpha__flag", '["a1","true"]')] == [{"kind": "pack", "name": "facts/a.yaml", "position": "2"}]
    assert viewer[("beta", '["s1"]')] == [{"kind": "pack", "name": "facts/b.yaml", "position": "3"}]
    # The alpha s1 is not the viewer's, nor any cell of it; the beta s1 is: typed by its relation.
    assert not any(rel.startswith("alpha") and "s1" in key for rel, key in viewer)
    checker = {(x["row"]["relation"], x["row"]["key"]) for x in role_sources(s, m, "checker")}
    assert {("alpha", '["s1"]'), ("alpha__flag", '["s1","false"]'), ("beta", '["s1"]')} <= checker


def test_a_sidecars_exact_sources_reach_the_role_with_the_row(tmp_path):
    side = {"default": GIT, "records": [{"of": {"kind": "beta", "id": "b1"}, "position": "rows.json#/1"}]}
    s, m = published(tmp_path, epoch(pack(tmp_path, side)))
    viewer = {(x["row"]["relation"], x["row"]["key"]): x["sources"] for x in role_sources(s, m, "viewer")}
    assert viewer[("beta", '["b1"]')] == [GIT | {"position": "rows.json#/1"}]
    assert viewer[("beta__state", '["s1","high"]')] == [GIT]



def lookup(pieces: dict, root: dict, key: list):
    """One row's leaf entry, as the gate reads it: one piece per level, each by the sha256 its parent names."""
    data = pieces[views.key_of(root["uri"])]
    assert views.sha256(data) == root["sha256"]
    piece, at = json.loads(data), [p.encode() for p in key]
    while "children" in piece:
        child = next((c for c in piece["children"] if [p.encode() for p in c["first"]] <= at <= [p.encode() for p in c["last"]]), None)
        if child is None:
            return None
        data = pieces[next(k for k in pieces if k.endswith("/" + child["file"]))]
        assert views.sha256(data) == child["sha256"]
        piece = json.loads(data)
    return next((r for r in piece["rows"] if r["key"] == key), None)


def test_the_views_carry_each_roles_sources_as_trees_by_row(tmp_path):
    """S25 step 6a for O(page): beside the proof pieces, the view index lists the role's source entries
    as key-range trees by row, checked against the set the manifest names, so the gate reads one row's sources
    with one lookup and never the whole set. A manifest without a source set (before S25) gets no trees."""
    side = {"default": GIT, "records": [{"of": {"kind": "beta", "id": "b1"}, "position": "rows.json#/1"}]}
    s, m = published(tmp_path, epoch(pack(tmp_path, side)))
    for role in ROLES:
        [ref] = [x for x in m["fact_sources"] if x["role"] == role]
        made, part = views._sources(s, "minimal", m["id"], m, role)
        pieces = dict(made)
        assert all(k.startswith(f"minimal/{m['id']}/{role}/views/sources/") for k in pieces)
        assert (part["format"], part["set"], part["piece"], part["fanout"]) == (views.SOURCES, ref["sha256"], 65536, 128)
        entries = role_sources(s, m, role)
        assert set(part["trees"]) == {x["row"]["relation"] for x in entries}
        for x in entries:
            got = lookup(pieces, part["trees"][x["row"]["relation"]], json.loads(x["row"]["key"]))
            assert got == {"key": json.loads(x["row"]["key"])} | {k: v for k, v in x.items() if k != "row"}
        if role == "viewer":  # a row the role does not read has no entry: the alpha s1 is the checker's only
            assert lookup(pieces, part["trees"]["beta"], ["b1"])["sources"] == [GIT | {"position": "rows.json#/1"}]
            assert "alpha" not in part["trees"] or lookup(pieces, part["trees"]["alpha"], ["s1"]) is None
    assert views._sources(s, "minimal", m["id"], {k: v for k, v in m.items() if k != "fact_sources"}, "viewer") == ([], None)

# A readable beta whose sources name a line 3 and the texts x and s1: the ids of hidden elements in one world.
NAMING = {"default": GIT | {"name": "example/x"},
          "records": [{"of": {"kind": "beta", "id": "b1"}, "position": "rows.json#3/s1"}]}
HIDDEN_X = "  - {id: x, title: closed, size: 1, flag: false}\n"


def viewer_sources(tmp: Path, **world) -> tuple[bytes, dict]:
    s, m = published(tmp, epoch(pack(tmp, NAMING, **world)))
    [ref] = [x for x in m["fact_sources"] if x["role"] == "viewer"]
    return get(s, ref["uri"]), ref


def test_hidden_rows_change_no_byte_of_a_roles_sources(tmp_path):
    """S25: a source follows its readable row as a declared unit.
    Adding a hidden gamma 3 and a hidden alpha x, or removing the hidden alpha s1, changes nothing the viewer
    gets: not its source bytes, not their hash, not whether they are published. A line 3 is not the element
    gamma/3, and equal text is no access relation."""
    base, ref = viewer_sources(tmp_path / "base")
    more, more_ref = viewer_sources(tmp_path / "more", alphas=ALPHAS + HIDDEN_X, gammas="gamma:\n  - {id: 3}\n")
    less, less_ref = viewer_sources(tmp_path / "less", alphas=ALPHAS.split("  - {id: s1")[0])
    assert base == more == less and ref["sha256"] == more_ref["sha256"] == less_ref["sha256"]
    b1 = next(x for x in json.loads(base) if x["row"] == {"relation": "beta", "key": '["b1"]'})
    assert b1["sources"] == [GIT | {"name": "example/x", "position": "rows.json#3/s1"}]
    # The complete role reads them, so its own sources change with the facts.
    s, m = published(tmp_path / "check", epoch(pack(tmp_path / "check", NAMING, gammas="gamma:\n  - {id: 3}\n")))
    assert ("gamma", '["3"]') in {(x["row"]["relation"], x["row"]["key"]) for x in role_sources(s, m, "checker")}
    assert not any(x["row"]["relation"] == "gamma" for x in json.loads(base))


def test_an_invalid_source_blocks_before_any_write(tmp_path):
    e = epoch(pack(tmp_path))
    unpinned = [{"kind": "git", "name": "example/register", "position": "rows.json"}]  # git without a revision
    broken = [x | {"sources": unpinned} if x["row"] == {"relation": "beta", "key": '["b1"]'} else x
              for x in e.fact_sources]
    s = store.FileStore(tmp_path / "store")
    with pytest.raises(publish.Blocked) as err:
        publish.publish(dataclasses.replace(e, fact_sources=broken), s, ROLES)
    assert s.list("") == [], "no publication write"
    assert str(err.value) == 'rezono:sources: role checker: source_fields (first: source_fields beta ["b1"] revision)'


@pytest.mark.parametrize("change", ["missing", "stale", "unsorted_is_fixed"])
def test_a_wrong_entry_blocks_before_any_write(tmp_path, change):
    e = epoch(pack(tmp_path))
    entries = list(e.fact_sources)
    if change == "missing":  # the viewer's beta b1 without its sources
        entries = [x for x in entries if x["row"] != {"relation": "beta", "key": '["b1"]'}]
    elif change == "stale":  # an entry for a row that is not in the epoch
        entries.append({"row": {"relation": "beta", "key": '["gone"]'}, "sources": [GIT]})
    else:  # the publisher orders the entries and their sources itself
        entries = list(reversed(entries))
    s = store.FileStore(tmp_path / "store")
    if change == "unsorted_is_fixed":
        a, _ = published(tmp_path / "a", e)
        b, _ = published(tmp_path / "b", dataclasses.replace(e, fact_sources=entries))
        assert all(a.get(k) == b.get(k) for k in a.list("")) and a.list("") == b.list("")
        return
    with pytest.raises(publish.Blocked, match="rezono:sources"):
        publish.publish(dataclasses.replace(e, fact_sources=entries), s, ROLES)
    assert s.list("") == []


def test_the_bytes_are_the_same_every_time(tmp_path):
    e = epoch(pack(tmp_path / "p"))
    a, m = published(tmp_path / "a", e)
    b, n = published(tmp_path / "b", epoch(pack(tmp_path / "q")))
    assert m == n and a.list("") == b.list("") and all(a.get(k) == b.get(k) for k in a.list(""))
    again = publish.publish(e, a, ROLES)  # the same epoch again: a no-op, the same manifest
    assert again == m
    for x in m["fact_sources"]:
        assert x["uri"] == a.uri(f"minimal/objects/{x['sha256']}.json")


def test_a_later_epoch_names_the_base_source_set_when_its_bytes_are_the_same(tmp_path):
    e = epoch(pack(tmp_path))
    s, m = published(tmp_path, e)
    files, n = publish.plan(dataclasses.replace(e, epoch=2, base_manifest="m-1"), s, ROLES, m)
    assert n["fact_sources"] == m["fact_sources"]
    assert not {x["uri"].removeprefix(s.uri("")) for x in n["fact_sources"]} & dict(files).keys()
    # A base from before S25 lists no source set: the files are written anew, the base is still read.
    old = {k: v for k, v in m.items() if k != "fact_sources"}
    files, n = publish.plan(dataclasses.replace(e, epoch=2, base_manifest="m-1"), s, ROLES, old)
    assert n["fact_sources"] == m["fact_sources"]
    assert {x["uri"].removeprefix(s.uri("")) for x in n["fact_sources"]} <= dict(files).keys()


def test_an_epoch_without_source_entries_publishes_as_before(tmp_path):
    """An older caller supplies none: no source set and no `rezono:sources` check, the rest unchanged."""
    e = epoch(pack(tmp_path))
    _, m = published(tmp_path / "with", e)
    _, old = published(tmp_path / "without", dataclasses.replace(e, fact_sources=None))
    assert "fact_sources" not in old and all(c["name"] != "rezono:sources" for c in old["checks"])
    same = lambda x: {k: v for k, v in x.items() if k not in ("fact_sources", "checks")}
    assert same(old) == same(m)


def test_a_boolean_key_is_the_snapshots_text():
    assert fact_sources.snapshot_key('["a1",true]') == '["a1","true"]'
    assert fact_sources.snapshot_key('["7","2026-01-01"]') == '["7","2026-01-01"]'
    with pytest.raises(fact_sources.Stale):
        fact_sources.snapshot_key('{"a":1}')
