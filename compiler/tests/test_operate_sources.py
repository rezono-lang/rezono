"""Sources through schema operations (B12, seam S6; docs/compiler.md#provenance-per-fact-s25).

An operation either carries every exact origin to the rows its content goes to, or refuses and changes nothing.
The inverse operation gives the companion back byte for byte. A row the operation loses takes its sources with
it, and the impact lists it.
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, assume, given, settings, strategies as st

import genpack
from rezono_canon import canonical_json
from rezono_compiler import operate, sources, writer
from rezono_compiler import pack as packs
from operation_source_support import companion, library, origin, per_record  # noqa: F401
from test_operate import COMBINE, DROPS, MOVES, RENAMES, SPLIT, combine_ops, files, move_ops, run, \
    split_ops


def by_ref(d: Path, fname: str = "valid.yaml") -> dict:
    path = d / "facts" / fname
    return {(e["row"]["relation"], e["row"]["key"]): e for e in sources.file_entries(packs.read(d), path)}


def origins(entries: dict) -> Counter:
    return Counter(canonical_json(e["sources"]) for e in entries.values())


def test_a_pack_without_companions_runs_as_before(library, tmp_path):
    impact, _ = run(library, [RENAMES[0][0]], tmp_path)
    assert "sources" not in impact["operations"][0]
    assert not list((library / "facts").glob("*.sources.yaml"))


@pytest.mark.parametrize("op, inverse, _", RENAMES, ids=lambda x: str(x.get("to")) if isinstance(x, dict) and "op" in x else "")
def test_a_rename_carries_each_origin_and_the_rename_back_gives_the_companion_bytes_back(library, tmp_path, op, inverse, _):
    original = companion(library)
    before = by_ref(library)
    impact, _ = run(library, [op], tmp_path)
    o = impact["operations"][0]
    assert o["sources"] == {"companions": ["facts/valid.sources.yaml"], "lost": []}
    after = by_ref(library)
    assert origins(after) == origins(before), "an isomorphism keeps every origin, once per row"
    run(library, [inverse], tmp_path, "back")
    assert (library / "facts" / "valid.sources.yaml").read_bytes() == original


def test_a_renamed_row_keeps_the_origin_of_its_own_row(library, tmp_path):
    companion(library)
    want = by_ref(library)[("copy", '["1001"]')]["sources"]
    run(library, [RENAMES[0][0]], tmp_path)  # Copy -> Item
    assert by_ref(library)[("item", '["1001"]')]["sources"] == want


@pytest.mark.parametrize("op, inverse, lossless, tables", MOVES, ids=lambda x: str(x.get("to")) if isinstance(x, dict) and "op" in x else "")
def test_a_move_carries_origins_and_its_inverse_gives_the_companion_back(library, tmp_path, op, inverse, lossless, tables):
    # One origin per record: a value copied to several elements keeps its one origin; moving it back merges
    # rows with the same origin only.
    original = companion(library, of=lambda ref, n: [origin(f"{ref[0].split('__')[0]}-{yaml.safe_load(ref[1])[0]}")])
    before = by_ref(library)
    impact, _ = run(library, [op], tmp_path)
    o = impact["operations"][0]
    after = by_ref(library)
    assert set(origins(after)) <= set(origins(before)), "no origin is invented"
    lost = {(x["relation"], x["key"]) for x in o["sources"]["lost"]}
    assert bool(lost) != lossless
    assert all(t == tables[0] for t, _ in lost)
    if inverse:
        run(library, [inverse], tmp_path, "back")
        assert (library / "facts" / "valid.sources.yaml").read_bytes() == original


def test_a_move_that_would_merge_different_origins_refuses_and_changes_nothing(library, tmp_path):
    """Two copies of w1 carry its title from different origins: moving the title back to the work would give
    w1 one title from two origins, which no undo can split again."""
    companion(library)  # one origin per row
    run(library, [MOVES[2][0]], tmp_path)  # Work.title -> Copy
    assert len({canonical_json(by_ref(library)[("copy__title", f'["{c}","De avonden"]')]["sources"]) for c in (1001, 1002)}) == 1
    path = library / "facts" / "valid.sources.yaml"
    doc = yaml.safe_load(path.read_text("utf-8"))
    for e in doc["rows"]:
        if e["row"] == {"relation": "copy__title", "key": '["1002","De avonden"]'}:
            e["sources"] = [origin("another register")]
    path.write_text(canonical_json(doc) + "\n", encoding="utf-8")
    before = files(library)
    with pytest.raises(operate.OperationError, match=r"exact origin(.|\n)*work__title .*rows of different origins merged"):
        run(library, [MOVES[2][1]], tmp_path, "back")
    assert files(library) == before


def test_a_value_from_a_file_without_a_companion_into_one_with_refuses(library, tmp_path):
    valid = library / "facts" / "valid.yaml"
    text = valid.read_text("utf-8")
    line = "  - {id: w2, title: Moord in de leeszaal, category: c2, authors: [A. Schrijver, B. Schrijver]}\n"
    valid.write_text(text.replace(line, ""), encoding="utf-8")
    (library / "facts" / "more.yaml").write_text("work:\n" + line, encoding="utf-8")
    companion(library)
    before = files(library)
    with pytest.raises(operate.OperationError, match=r'copy__title \["1003".*a row of a file without a companion'):
        run(library, [MOVES[2][0]], tmp_path)
    assert files(library) == before, "the rollback gives the companion back and writes no other"


def test_a_value_with_an_origin_gives_a_file_without_a_companion_one_or_refuses(library, tmp_path):
    """The move writes w2's title into copy 1003's record; when that record is in a file without a companion,
    the file gets one only if every row in it has an exact origin, which pack lines are not."""
    valid = library / "facts" / "valid.yaml"
    line = "  - {barcode: 1003, work: w2, branch: centrum, reference_only: true}\n"
    valid.write_text(valid.read_text("utf-8").replace(line, ""), encoding="utf-8")
    (library / "facts" / "more.yaml").write_text("copy:\n" + line, encoding="utf-8")
    companion(library)
    before = files(library)
    with pytest.raises(operate.OperationError, match=r'facts/more.yaml: copy \["1003"\]: a row of a file without a companion'):
        run(library, [MOVES[2][0]], tmp_path)
    assert files(library) == before


def test_the_same_row_in_two_files_with_a_companion_refuses(library, tmp_path):
    (library / "facts" / "more.yaml").write_text("category:\n  - {id: c3, name: Natuur}\n", encoding="utf-8")
    companion(library)
    companion(library, "more.yaml", of=lambda ref, n: [origin(f"more-{n}")])
    before = files(library)
    with pytest.raises(operate.OperationError, match="a row of two files"):
        run(library, [{"op": "rename", "kind": "Category", "to": "Genre"}], tmp_path)
    assert files(library) == before


def test_a_drop_loses_the_sources_of_the_rows_it_loses_and_keeps_every_other(library, tmp_path):
    companion(library)
    before = by_ref(library)
    impact, _ = run(library, [DROPS[0][0]], tmp_path)  # Copy.reference_only
    lost = {(x["relation"], x["key"]) for x in impact["operations"][0]["sources"]["lost"]}
    assert lost == {r for r in before if r[0] == "copy__reference_only"} and len(lost) == 3
    assert by_ref(library) == {r: e for r, e in before.items() if r not in lost}


@pytest.mark.parametrize("op", [SPLIT, SPLIT | {"abstract": True}, COMBINE], ids=["split", "split-abstract", "combine"])
def test_split_and_combine_carry_every_origin(library, tmp_path, op):
    companion(library, of=per_record)
    before = by_ref(library)
    impact, _ = run(library, [op], tmp_path)
    assert impact["operations"][0]["sources"]["lost"] == []
    assert set(origins(by_ref(library))) == set(origins(before))


def test_a_combine_that_would_drop_the_own_origin_of_an_absorbed_element_refuses(library, tmp_path):
    """With one origin per row, the address element's own row and the arrow to it carry origins that only
    route the street and city into the branch: after the combine nothing would hold them."""
    companion(library)
    before = files(library)
    with pytest.raises(operate.OperationError, match=r'branch__address \["centrum".*an origin only routed'):
        run(library, [COMBINE], tmp_path)
    assert files(library) == before


def test_a_companion_that_does_not_load_blocks_before_any_change(library, tmp_path):
    (library / "facts" / "valid.sources.yaml").write_text('{"rows":[{"row":{"relation":"nope","key":"[1]"},'
                                                          '"sources":[{"kind":"person","name":"r","position":"p"}]}]}\n')
    before = files(library)
    with pytest.raises(operate.OperationError, match="source companions do not load"):
        run(library, [RENAMES[0][0]], tmp_path)
    assert files(library) == before


# --- Random operations over generated packs -------------------------------------------------------------------

def inverse_of(op: dict, p) -> dict | None:
    """The rename that undoes a rename of a generated pack."""
    if op["op"] != "rename":
        return None
    if "enum" in op:
        return {"op": "rename", "enum": op["enum"], "value": op["to"], "to": op["value"]}
    if "slot" in op:
        return {"op": "rename", "kind": op["kind"], "slot": op["to"], "to": op["slot"]}
    return {"op": "rename", "kind": op["to"], "to": op["kind"]}


@settings(max_examples=60, deadline=None, derandomize=True, database=None, suppress_health_check=list(HealthCheck))
@given(st.data())
def test_random_operations_carry_sources_or_refuse(data):
    """For a generated pack with a companion of random origins (a few, so equal origins meet) and a random
    operation: the operation refuses and changes no byte, or the companions load, no origin is invented, every
    origin is carried or its row is listed as lost, and a rename back gives the companion back byte for byte."""
    spec = genpack.draw_spec(data.draw)
    assume(not spec.refused())
    state = genpack.draw_state(data.draw, spec)
    work = writer.work_dir()
    try:
        d = work / "generated"
        genpack.write_pack(spec, d)
        (d / "facts").mkdir()
        (d / "facts" / "state.yaml").write_text(yaml.safe_dump(state.records(), sort_keys=True))
        try:
            p = packs.read(d)
            refs = [(e["row"]["relation"], e["row"]["key"]) for e in
                    sources.text_entries(p, "state.yaml", (d / "facts" / "state.yaml").read_text("utf-8"))]
        except (packs.CompileError, ValueError):
            assume(False)
        assume(refs)
        pool = data.draw(st.integers(1, 3))
        drawn = [data.draw(st.integers(0, pool - 1)) for _ in refs]
        original = companion(d, "state.yaml", of=lambda ref, n: [origin(f"origin-{drawn[n]}")])
        before = by_ref(d, "state.yaml")
        ops = [{"op": "rename", "kind": k.cls, "to": "Renamed"} for k in p.kinds.values()]
        ops += [{"op": "rename", "kind": k.cls, "slot": s, "to": "renamed"} for k in p.kinds.values() for s in k.slots]
        ops += [{"op": "rename", "enum": e.upper(), "value": v,
                 "to": next(f"v{i}" for i in range(9, -1, -1) if f"v{i}" not in vs)} for e, vs in p.enums.items()
                for v in vs]
        ops += [{"op": "drop", "kind": k.cls, "accept_loss": True} for k in p.kinds.values()]
        ops += [{"op": "drop", "kind": k.cls, "slot": x, "accept_loss": True} for k in p.kinds.values() for x in k.slots]
        ops += move_ops(p) + split_ops(p) + combine_ops(p)
        op = data.draw(st.sampled_from(sorted(ops, key=repr)))
        before_files = files(d)
        try:
            impact, _ = run(d, [op], work)
        except operate.OperationError:
            assert files(d) == before_files
            return
        o = impact["operations"][0]
        after = by_ref(d, "state.yaml")
        assert set(origins(after)) <= set(origins(before)), "an origin was invented"
        lost = {(x["relation"], x["key"]) for x in o["sources"]["lost"]}
        assert lost <= set(before)
        if not lost:
            assert set(origins(after)) == set(origins(before)) or not after, "an origin went without a lost row"
        if o["lossless"]:
            assert not lost
        back = inverse_of(op, p)
        if back is not None:
            run(d, [back], work, "back")
            assert (d / "facts" / "state.sources.yaml").read_bytes() == original
    finally:
        shutil.rmtree(work, ignore_errors=True)
