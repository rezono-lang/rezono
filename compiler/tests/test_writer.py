"""The canonical writer: every example fact file reads and writes back to the same bytes, any sequence of
edits followed by its undo gives the same bytes again, and the writer never writes outside the pack or
leaves a half-written file (docs/compiler.md#the-canonical-writer)."""

from __future__ import annotations

import collections
import datetime
import functools
import json
import shutil
import time
import warnings
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings, strategies as st

from rezono_compiler import facts, modules, writer

REPO = Path(__file__).resolve().parents[2]
PACKS = sorted(p.parent for p in (REPO / "examples").rglob("pack.yaml") if "expected" not in p.parts)
# A source companion (facts/<file>.sources.yaml, S25) is no fact file: test_writer_sources.py covers it.
FILES = [(d, f) for d in PACKS for f in sorted((d / "facts").glob("*.yaml")) if not f.name.endswith(".sources.yaml")]
IDS = [str(f.relative_to(REPO)) for _, f in FILES]
# Random edits read the file a few times per step (± 30 ms at 50 kB), so larger files get fewer examples;
# the largest (generated) files get a fixed delta of their own, with its time measured.
SMALL = [(d, f) for d, f in FILES if f.stat().st_size <= 16_000]
MEDIUM = [(d, f) for d, f in FILES if 16_000 < f.stat().st_size <= 64_000]
LARGE = [(d, f) for d, f in FILES if f.stat().st_size > 64_000]


@functools.lru_cache(maxsize=None)
def layout(pack_dir: Path) -> writer.Layout:
    return writer.layout(pack_dir)


def read(path: Path, crlf: bool = False) -> str:
    """The file's real text: no newline translation (read_text would turn CRLF into LF)."""
    text = path.read_bytes().decode("utf-8")
    return text.replace("\n", "\r\n") if crlf else text


def ids(files):
    return [str(f.relative_to(REPO)) for _, f in files]


def test_there_are_fact_files():
    assert FILES, "no example pack with fact files"


@pytest.mark.parametrize("crlf", [False, True], ids=["lf", "crlf"])
@pytest.mark.parametrize("pack_dir,path", FILES, ids=IDS)
def test_read_and_write_back_gives_the_same_bytes(pack_dir, path, crlf):
    text = read(path, crlf)
    assert writer.canonical(layout(pack_dir), text).encode("utf-8") == text.encode("utf-8")


# --- Values ----------------------------------------------------------------------------------------

TEXT = st.text(st.characters(codec="utf-8"), max_size=12)
TRICKY = st.sampled_from(["", " a", "a ", "true", "no", "null", "~", "123", "-5", "0x1F", "1:20", "2026-10-01",
                          "a: b", "a #b", "#a", "'a'", '"a"', "a,b", "[a]", "{a}", "é", "a\nb", "\t", "\x85",
                          "\u2028", "\ufeff", ".inf", "@a", "%a", "- a", "?", "a'b", 'a"b', "a\\b", "a\r\nb"])


@given(st.one_of(TEXT, TRICKY))
def test_quoted_text_reads_back(s):
    q = writer.quote(s)
    assert yaml.safe_load("{k: " + q + "}") == {"k": s}
    assert yaml.safe_load("k: " + q + "\n") == {"k": s}
    j = writer.json_text(s)  # the JSON dialect: valid JSON, and YAML reads it back the same
    assert json.loads(j) == s
    assert yaml.safe_load("{k: " + j + "}") == {"k": s}


def test_quoting_is_fixed():
    assert [writer.quote(s) for s in ["Markt 1", "4331 LK", "true", "a: b", "", "a\nb"]] == \
        ["Markt 1", "4331 LK", "'true'", "'a: b'", "''", '"a\\nb"']


# --- Random edits and their undo -------------------------------------------------------------------

def scalar_values(lay: writer.Layout, slot) -> st.SearchStrategy:
    p = lay.pack
    sql_type = p.kinds[p.root(slot.range)].id_type if slot.arrow else slot.sql_type
    if sql_type == "BIGINT":
        n = st.integers(-(2**63), 2**63 - 1)
        return st.one_of(n, n.map(str))  # decimal text is the canonical JSON form
    if sql_type == "BOOLEAN":
        return st.booleans()
    if sql_type == "DATE":
        return st.dates().map(lambda d: d.isoformat())
    if slot.enum:
        return st.one_of(st.sampled_from(p.enums[slot.enum]), TEXT)
    return st.one_of(TEXT, TRICKY)


def values_for(lay: writer.Layout, slot, depth: int = 0) -> st.SearchStrategy:
    if slot.inlined:
        one = record_values(lay, slot.range, depth + 1) if depth < 2 else st.just({})
    else:
        one = scalar_values(lay, slot)
    return st.one_of(one, st.lists(one, min_size=2, max_size=2)) if not slot.inlined else one


def record_values(lay: writer.Layout, kind: str, depth: int = 0) -> st.SearchStrategy:
    ident = lay.pack.kinds[lay.pack.root(kind)].identifier
    slots = [s for s in lay.pack.all_slots(kind) if s.name != ident]
    return st.fixed_dictionaries({}, optional={s.name: values_for(lay, s, depth) for s in slots})


def editable(lay: writer.Layout) -> list[str]:
    p = lay.pack
    return [k for k in sorted(p.kinds) if not p.kinds[k].abstract and p.kinds[p.root(k)].identifier]


def unique_records(lay: writer.Layout, text: str) -> list[tuple[str, object, dict]]:
    """(kind, key, record) for every record whose key appears once: those a change can name."""
    _, sections, data = writer.parse(text)
    out = []
    for sec in sections:
        ident = lay.identifier(sec.kind)[0]
        recs = data.get(sec.kind) or []
        count = collections.Counter(repr(r.get(ident)) for r in recs)
        out += [(sec.kind, r[ident], r) for r in recs if count[repr(r.get(ident))] == 1]
    return out


@st.composite
def change(draw, lay: writer.Layout, text: str):
    """Any change that names an existing record or a new key: also records with comments, records whose
    slots are not in schema order and records out of identifier order."""
    present = unique_records(lay, text)
    op = draw(st.sampled_from(["insert"] + (["delete", "set", "unset"] if present else [])))
    if op == "insert":
        _, _, data = writer.parse(text)
        kind = draw(st.sampled_from(editable(lay)))
        ident, id_type = lay.identifier(kind)
        taken = {writer.to_json(r.get(ident)) for r in data.get(kind) or [] if isinstance(r, dict)}
        key = draw((st.integers(-(10**6), 10**6).map(str) if id_type == "BIGINT" else st.one_of(TEXT, TRICKY))
                   .filter(lambda k: k not in taken))
        return {"op": "insert", "kind": kind, "key": key, "values": draw(record_values(lay, kind))}
    kind, key, rec = draw(st.sampled_from(present))
    ident = lay.identifier(kind)[0]
    base = {"kind": kind, "key": writer.to_json(key)}
    slots = [s for s in lay.pack.all_slots(kind) if s.name != ident]
    filled = [n for n in rec if n != ident]
    # A kind with an identifier only (a subject the facts merely name) has no slot to set or unset.
    if op == "delete" or (op == "unset" and not filled) or (op == "set" and not slots):
        return {"op": "delete", **base}
    if op == "set":
        s = draw(st.sampled_from(slots))
        return {"op": "set", **base, "slot": s.name, "value": draw(values_for(lay, s))}
    return {"op": "unset", **base, "slot": draw(st.sampled_from(filled))}


def facts_of(text: str) -> dict:
    """The facts as the pack's loader types them: a date and its ISO text are one fact. The JSON dialect writes
    a date as text, and a file emptied of records no longer says which dialect it had, so an undo from values
    may write the date bare."""
    return writer.as_written(yaml.safe_load(text) or {}, True)


def edits_and_undo(pack_dir, path, data, crlf=False):
    lay = layout(pack_dir)
    original = text = read(path, crlf)
    undo = []
    for _ in range(data.draw(st.integers(1, 6))):
        text, inverse = writer.apply_change(lay, text, data.draw(change(lay, text)))
        assert "\r" not in text.replace("\r\n", "") and text.endswith("\n")
        if crlf:
            assert "\n" not in text.replace("\r\n", ""), "every line keeps the file's CRLF"
        undo.insert(0, inverse)
    back, _ = writer.apply(lay, text, undo)
    assert back.encode("utf-8") == original.encode("utf-8")  # exact: comments, quoting, order and place
    loose, _ = writer.apply(lay, text, [{k: v for k, v in c.items() if k != "restore"} for c in undo])
    assert writer.same_facts(facts_of(loose), facts_of(original), ordered_rows=False), \
        "without its exact lines, an undo still gives the same facts"


@pytest.mark.parametrize("pack_dir,path", SMALL, ids=ids(SMALL))
@given(data=st.data())
def test_edits_and_their_undo_give_the_same_bytes(pack_dir, path, data):
    edits_and_undo(pack_dir, path, data)


@pytest.mark.parametrize("pack_dir,path", SMALL, ids=ids(SMALL))
@settings(max_examples=25)
@given(data=st.data())
def test_edits_and_their_undo_keep_crlf(pack_dir, path, data):
    edits_and_undo(pack_dir, path, data, crlf=True)


@pytest.mark.parametrize("pack_dir,path", SMALL, ids=ids(SMALL))
def test_deleting_every_record_and_the_undo_give_the_same_bytes(pack_dir, path):
    """The case random edits rarely reach: a file emptied of records no longer says which dialect it had, and
    its kinds are gone. The undo still gives the exact bytes back, and from values alone the same facts."""
    lay = layout(pack_dir)
    original = text = read(path)
    undo = []
    for kind, key, _ in unique_records(lay, original):
        text, inverse = writer.apply_change(lay, text, {"op": "delete", "kind": kind, "key": writer.to_json(key)})
        undo.insert(0, inverse)
    assert writer.apply(lay, text, undo)[0].encode("utf-8") == original.encode("utf-8")
    loose, _ = writer.apply(lay, text, [{k: v for k, v in c.items() if k != "restore"} for c in undo])
    assert writer.same_facts(facts_of(loose), facts_of(original), ordered_rows=False)


@pytest.mark.parametrize("pack_dir,path", MEDIUM, ids=ids(MEDIUM))
@settings(max_examples=25)
@given(data=st.data())
def test_edits_and_their_undo_on_a_larger_file(pack_dir, path, data):
    edits_and_undo(pack_dir, path, data)


def changed(lay: writer.Layout, kind: str, name: str, v):
    """Another value of the same type, as delta JSON."""
    s = lay.pack.slot(kind, name)
    if s is None or s.arrow or isinstance(v, (list, dict)):
        return None
    if s.sql_type == "BOOLEAN" and isinstance(v, bool):
        return not v
    if s.sql_type == "BIGINT" and isinstance(v, int) and not isinstance(v, bool):
        return str(v + 1)
    if s.sql_type == "DATE":
        d = v if isinstance(v, datetime.date) else datetime.date.fromisoformat(v)
        return (d + datetime.timedelta(days=1)).isoformat()
    if s.sql_type == "VARCHAR" and isinstance(v, str):
        return v + " (2)"
    return None


@pytest.mark.parametrize("pack_dir,path", LARGE, ids=ids(LARGE))
def test_a_delta_on_a_large_file_and_its_undo(pack_dir, path):
    """A fixed delta of ten changes spread over the file, and its undo. The time is a measurement
    (docs/ci.md: budgets as data): every change reads the whole file, so it grows with the file."""
    lay = layout(pack_dir)
    original = read(path)
    present = unique_records(lay, original)
    picks = [present[i * len(present) // 10] for i in range(10)]
    delta = []
    for kind, key, rec in picks[:8]:
        ident = lay.identifier(kind)[0]
        slot = next((n for n in rec if n != ident and changed(lay, kind, n, rec[n]) is not None), None)
        if slot is not None:
            delta.append({"op": "set", "kind": kind, "key": writer.to_json(key), "slot": slot,
                          "value": changed(lay, kind, slot, rec[slot])})
    kind, key, rec = picks[8]
    ident = lay.identifier(kind)[0]
    delta.append({"op": "insert", "kind": kind, "key": writer.to_json(key) + "-2",
                  "values": writer.to_json({k: v for k, v in rec.items() if k != ident})})
    delta.append({"op": "delete", "kind": picks[9][0], "key": writer.to_json(picks[9][1])})
    started = time.perf_counter()
    text, undo = writer.apply(lay, original, delta)
    forward = time.perf_counter() - started
    back, _ = writer.apply(lay, text, undo)
    total = time.perf_counter() - started
    assert back.encode("utf-8") == original.encode("utf-8")
    old, new = original.splitlines(), text.splitlines()
    assert len(set(new) - set(old)) <= len(delta), "only the changed records' lines are new"
    warnings.warn(f"measurement {path.relative_to(REPO)} ({path.stat().st_size // 1000} kB): "
                  f"{len(delta)} changes in {forward:.1f} s, with undo {total:.1f} s")


# --- Exact undo, also where the values alone cannot say it -----------------------------------------

def first_record(pack_dir: Path, path: Path) -> tuple[str, str, dict]:
    lay = layout(pack_dir)
    for kind, _, rec in unique_records(lay, read(path)):
        if kind in editable(lay):
            return kind, lay.identifier(kind)[0], rec
    pytest.skip("no record to edit")


def text_kind(lay: writer.Layout) -> tuple[str, str, list[str]] | None:
    """A kind with a text identifier and at least two text slots, for hand-made files."""
    for kind in editable(lay):
        ident, id_type = lay.identifier(kind)
        names = [s.name for s in lay.pack.all_slots(kind) if s.name != ident and not s.arrow and not s.inlined
                 and s.sql_type == "VARCHAR" and not s.enum]
        if id_type == "VARCHAR" and len(names) >= 2:
            return kind, ident, names
    return None


def test_undo_restores_comments_place_and_order():
    """A record with comments, its slots out of schema order, in a file out of identifier order: its
    undo gives the same bytes because it carries the exact lines; an unset keeps the comment."""
    found = next((t for d, _ in FILES if (t := text_kind(layout(d)))), None)
    if found is None:
        pytest.skip("no kind with a text identifier and two text slots")
    kind, ident, (a, b) = found[0], found[1], found[2][:2]
    lay = next(layout(d) for d, _ in FILES if text_kind(layout(d)) == found)
    text = (f"# header\n{kind}:\n  # about zz-9\n  - {{{b}: y, {ident}: zz-9, {a}: x}}   # note\n"
            f"  - {{{ident}: aa-1}}\n")
    out, inverse = writer.apply_change(lay, text, {"op": "delete", "kind": kind, "key": "zz-9"})
    assert "zz-9" not in out
    assert writer.apply_change(lay, out, inverse)[0] == text
    out, inverse = writer.apply_change(lay, text, {"op": "unset", "kind": kind, "key": "zz-9", "slot": b})
    assert out.splitlines()[3] == f"  - {{{ident}: zz-9, {a}: x}}   # note"
    assert writer.apply_change(lay, out, inverse)[0] == text
    out, inverse = writer.apply_change(lay, text, {"op": "set", "kind": kind, "key": "zz-9", "slot": a, "value": "w"})
    assert out.splitlines()[3] == f"  - {{{b}: y, {ident}: zz-9, {a}: w}}   # note", "only the value changes"
    assert writer.apply_change(lay, out, inverse)[0] == text


def test_comment_lines_between_slots_stay():
    found = next(((d, t) for d, _ in FILES if (t := text_kind(layout(d)))), None)
    if found is None:
        pytest.skip("no kind with a text identifier and two text slots")
    lay = layout(found[0])
    kind, ident, (a, b) = found[1][0], found[1][1], found[1][2][:2]
    text = f"{kind}:\n  - {ident}: k1\n    # about {a}\n    {a}: 'x'   # why\n    {b}: y\n"
    out, inverse = writer.apply_change(lay, text, {"op": "set", "kind": kind, "key": "k1", "slot": a, "value": "z"})
    assert out == text.replace(f"{a}: 'x'", f"{a}: z")
    assert writer.apply_change(lay, out, inverse)[0] == text
    out, inverse = writer.apply_change(lay, text, {"op": "unset", "kind": kind, "key": "k1", "slot": b})
    assert out == f"{kind}:\n  - {ident}: k1\n    # about {a}\n    {a}: 'x'   # why\n"
    assert writer.apply_change(lay, out, inverse)[0] == text


def test_set_on_text_with_a_block_style():
    """Text written with `|` or `>` ends with its line break: replacing it must not glue the next slot on."""
    found = next(((d, t) for d, _ in FILES if (t := text_kind(layout(d)))), None)
    if found is None:
        pytest.skip("no kind with a text identifier and two text slots")
    lay = layout(found[0])
    kind, ident, (a, b) = found[1][0], found[1][1], found[1][2][:2]
    for style in ("|", ">", "|-"):
        for last in (False, True):
            keep = "" if last else f"    {b}: keep\n"
            text = f"{kind}:\n  - {ident}: k1\n    {a}: {style}\n      line one\n      line two\n{keep}"
            out, inverse = writer.apply_change(lay, text, {"op": "set", "kind": kind, "key": "k1", "slot": a,
                                                           "value": "z"})
            assert out == f"{kind}:\n  - {ident}: k1\n    {a}: z\n{keep}", (style, last)
            assert writer.apply_change(lay, out, inverse)[0] == text
            out, inverse = writer.apply_change(lay, text, {"op": "unset", "kind": kind, "key": "k1", "slot": a})
            assert out == f"{kind}:\n  - {ident}: k1\n{keep}", (style, last)
            assert writer.apply_change(lay, out, inverse)[0] == text


def test_a_new_slot_after_a_record_without_a_final_newline():
    found = next(((d, t) for d, _ in FILES if (t := text_kind(layout(d)))), None)
    if found is None:
        pytest.skip("no kind with a text identifier and two text slots")
    lay = layout(found[0])
    kind, ident, (a, _) = found[1][0], found[1][1], found[1][2][:2]
    for row, expected in ((f"  - {ident}: k1", f"  - {ident}: k1\n    {a}: new\n"),
                          (f"  - {{{ident}: k1}}", f"  - {{{ident}: k1, {a}: new}}")):
        text = f"{kind}:\n{row}"
        out, inverse = writer.apply_change(lay, text, {"op": "set", "kind": kind, "key": "k1", "slot": a,
                                                       "value": "new"})
        assert out == f"{kind}:\n{expected}"
        assert writer.apply_change(lay, out, inverse)[0] == text


@pytest.mark.parametrize("empty,head", [("{kind}: []\n", "{kind}:\n"), ("{kind}: []", "{kind}:\n"),
                                        ("{kind}:   [ ]  # none yet\n", "{kind}:  # none yet\n"),
                                        ("{kind}: []\r\n", "{kind}:\r\n")])
def test_a_kind_written_as_an_empty_list_reads_writes_back_and_takes_a_record(empty, head):
    """`kind: []` says "no records" in so many words (a fact file of an example pack writes it so). The
    file reads and writes back to the same bytes, the first insert makes it a block list and keeps a comment
    after it, and the undo gives the exact bytes back. A flow list with records is still refused."""
    found = next(((d, t) for d, _ in FILES if (t := text_kind(layout(d)))), None)
    if found is None:
        pytest.skip("no kind with a text identifier and two text slots")
    lay = layout(found[0])
    kind, ident, (a, _) = found[1][0], found[1][1], found[1][2][:2]
    nl = "\r\n" if "\r" in empty else "\n"
    for before in ("", f"# header{nl}"):
        text = before + empty.format(kind=kind)
        assert writer.canonical(lay, text) == text
        out, inverse = writer.apply_change(lay, text, {"op": "insert", "kind": kind, "key": "k1", "values": {a: "x"}})
        assert out.startswith(before + head.format(kind=kind)) and out.endswith(nl) and "[" not in out.split("- ", 1)[0]
        assert yaml.safe_load(out) == {kind: [{ident: "k1", a: "x"}]}
        assert writer.apply_change(lay, out, inverse)[0] == text
    with pytest.raises(writer.WriteError, match="write the records as a block list"):
        writer.parse(f"{kind}: [{{{ident}: k1}}]\n")
    with pytest.raises(writer.WriteError, match="write the records as a block list"):
        writer.parse(f"{kind}: [\n]\n")


def test_a_duplicate_key_is_refused():
    found = next(((d, t) for d, _ in FILES if (t := text_kind(layout(d)))), None)
    if found is None:
        pytest.skip("no kind with a text identifier")
    lay, (kind, ident, _) = layout(found[0]), found[1]
    text = f"{kind}:\n  - {{{ident}: k1}}\n  - {{{ident}: k1}}\n"
    with pytest.raises(writer.WriteError, match="more than once"):
        writer.apply_change(lay, text, {"op": "delete", "kind": kind, "key": "k1"})


def test_other_line_breaks_are_refused():
    for text in ("a:\r  - {}\r", "a:\u2028"):
        with pytest.raises(writer.WriteError, match="LF or CRLF"):
            writer.parse(text)


# --- Delta, CLI, files and refusals ----------------------------------------------------------------

def pack_named(name: str) -> Path:
    found = [d for d in PACKS if yaml.safe_load((d / "pack.yaml").read_text("utf-8"))["name"] == name]
    assert len(found) == 1, f"no single example pack named {name}"
    return found[0]


@pytest.fixture
def work():
    """A private work dir, as the Git-host plugin makes one per proposal; thrown away afterwards."""
    d = writer.work_dir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_cli_applies_a_delta_and_its_inverse_undoes_it(work, tmp_path):
    pack_dir, path = FILES[0]
    pack = writer.checkout(pack_dir, work)
    target = pack / path.relative_to(pack_dir)
    original = target.read_bytes()
    kind, ident, rec = first_record(pack_dir, path)
    delta = {"format": writer.FORMAT, "pack": layout(pack_dir).pack.meta["name"], "changes": [
        {"op": "delete", "file": str(path.relative_to(pack_dir)), "kind": kind, "key": writer.to_json(rec[ident])},
    ]}
    (tmp_path / "delta.json").write_text(json.dumps(delta))
    assert writer.main(["apply", str(pack), str(tmp_path / "delta.json"), "--inverse", str(tmp_path / "undo.json")]) == 0
    facts.load(layout(pack_dir).pack, target)  # the compiler reads what the writer wrote
    assert target.read_bytes() != original
    assert writer.main(["apply", str(pack), str(tmp_path / "undo.json")]) == 0
    assert target.read_bytes() == original
    assert not list(target.parent.glob(".*.tmp")), "no temporary files stay behind"


def delete_first(pack_dir: Path, path: Path, tmp_path: Path) -> Path:
    kind, ident, rec = first_record(pack_dir, path)
    delta = {"format": writer.FORMAT, "changes": [
        {"op": "delete", "file": str(path.relative_to(pack_dir)), "kind": kind, "key": writer.to_json(rec[ident])}]}
    (tmp_path / "delta.json").write_text(json.dumps(delta))
    return tmp_path / "delta.json"


def test_the_writer_writes_only_in_a_work_dir(tmp_path):
    """Not in the repository, not in any other directory: only in a rezono-work-* dir under the temp dir."""
    pack_dir, path = FILES[0]
    delta = delete_first(pack_dir, path, tmp_path)
    before = path.read_bytes()
    assert writer.main(["apply", str(pack_dir), str(delta)]) == 1
    assert path.read_bytes() == before
    elsewhere = modules.copy_closure(pack_dir, tmp_path / "rezono-work-not-under-the-temp-dir" / "pack")
    assert writer.main(["apply", str(elsewhere), str(delta)]) == 1


def test_the_writer_never_writes_through_a_link(work, tmp_path):
    pack_dir, path = FILES[0]
    outside = modules.copy_closure(pack_dir, tmp_path / "outside")
    before = {p: p.read_bytes() for p in sorted(outside.rglob("*")) if p.is_file()}
    delta = delete_first(pack_dir, path, tmp_path)
    rel = path.relative_to(pack_dir)
    for linked in ("pack", "facts", "file"):
        pack = work / f"pack-{linked}"
        if linked == "pack":  # the pack itself is a link out of the work dir
            pack.symlink_to(outside, target_is_directory=True)
        else:
            pack = writer.checkout(pack_dir, pack)
            if linked == "facts":  # facts/ points out of the pack
                shutil.rmtree(pack / "facts")
                (pack / "facts").symlink_to(outside / "facts", target_is_directory=True)
            else:  # the fact file points out of the pack
                (pack / rel).unlink()
                (pack / rel).symlink_to(outside / rel)
        assert writer.main(["apply", str(pack), str(delta)]) == 1, linked
    assert {p: p.read_bytes() for p in sorted(outside.rglob("*")) if p.is_file()} == before


def test_a_failed_write_leaves_no_half_file_and_says_to_discard(work, monkeypatch):
    pack_dir, path = FILES[0]
    pack = writer.checkout(pack_dir, work)
    target = pack / path.relative_to(pack_dir)
    before = target.read_bytes()

    def broken(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(writer.os, "replace", broken)
    with pytest.raises(writer.WriteError, match="discard the work dir"):
        writer.write_files(pack, {str(path.relative_to(pack_dir)): read(path) + "# changed\n"})
    assert target.read_bytes() == before, "the file is replaced whole or not at all"
    assert not list(target.parent.glob(".*.tmp"))


def test_contract_fixtures_apply():
    """The valid delta fixtures in contracts/ name an example pack and apply to it."""
    fixtures = sorted((REPO / "contracts" / "fixtures" / "delta" / "Delta" / "valid").glob("*.yaml"))
    assert fixtures
    for f in fixtures:
        delta = yaml.safe_load(f.read_text("utf-8"))
        if "sources" in delta:  # an undo of a fact file with a source companion fits only the bytes it was made for
            continue
        pack_dir = pack_named(delta["pack"])
        texts, undo = writer.apply_delta(pack_dir, delta, layout(pack_dir))
        for rel, text in texts.items():
            original = writer.read_fact_file(pack_dir, rel)
            back, _ = writer.apply(layout(pack_dir), text, [c for c in undo["changes"] if c["file"] == rel])
            assert back == original, f.name


@pytest.mark.parametrize("bad,message", [
    ({"op": "insert", "values": {"no_such_slot": "x"}}, "has no slot"),
    ({"op": "delete"}, "not found"),
    ({"op": "set", "slot": "@ident", "value": "x"}, "identifier does not change"),
    ({"op": "move"}, "op must be one of"),
])
def test_refusals(bad, message):
    pack_dir, path = FILES[0]
    lay = layout(pack_dir)
    kind, ident, rec = first_record(pack_dir, path)
    missing = "no-such-key-0" if lay.identifier(kind)[1] == "VARCHAR" else "987654321"
    ch = {"kind": kind, "key": writer.to_json(rec[ident]), **bad}
    if ch.get("slot") == "@ident":
        ch["slot"] = ident
    if ch["op"] in ("insert", "delete"):
        ch["key"] = missing
    with pytest.raises(writer.WriteError, match=message):
        writer.apply_change(lay, read(path), ch)


def test_a_restore_that_does_not_fit_falls_back_to_the_values():
    pack_dir, path = FILES[0]
    lay = layout(pack_dir)
    kind, ident, rec = first_record(pack_dir, path)
    text = read(path)
    out, inverse = writer.apply_change(lay, text, {"op": "delete", "kind": kind, "key": writer.to_json(rec[ident])})
    stale = {**inverse, "restore": {**inverse["restore"], "at": inverse["restore"]["at"] + 10_000}}
    back, _ = writer.apply_change(lay, out, stale)
    assert writer.same_facts(facts_of(back), facts_of(text), ordered_rows=False)
    wrong = {**inverse, "restore": {**inverse["restore"], "new": inverse["restore"]["new"] + inverse["restore"]["new"]}}
    with pytest.raises(writer.WriteError):
        writer.apply_change(lay, out, wrong)


def test_no_floats():
    pack_dir, path = FILES[0]
    lay = layout(pack_dir)
    numeric = [(k, s) for k in editable(lay) for s in lay.pack.all_slots(k) if s.sql_type == "BIGINT" and not s.arrow]
    if not numeric:
        pytest.skip("no whole-number slot")
    with pytest.raises(writer.WriteError, match="is not a BIGINT"):
        writer.typed(lay, numeric[0][0], numeric[0][1].name, 1.5, "x")


def test_a_change_without_a_file_goes_to_the_one_file_that_holds_its_record():
    """The viewer knows records, not files: the writer finds the file, and the undo delta names it. A record
    in no file, or in more than one, is refused; a new record names its file."""
    pack_dir = pack_named("library")
    lay = layout(pack_dir)
    change = {"op": "set", "kind": "work", "key": "w3", "slot": "year", "value": "1500"}
    texts, undo = writer.apply_delta(pack_dir, {"format": writer.FORMAT, "changes": [change]}, lay)
    assert list(texts) == ["facts/errors.yaml"]
    assert [c["file"] for c in undo["changes"]] == ["facts/errors.yaml"]
    named, _ = writer.apply_delta(pack_dir, {"format": writer.FORMAT, "changes": [{**change, "file": "facts/errors.yaml"}]}, lay)
    assert named == texts, "the same as with the file named"
    for key, message in (("w1", "in facts/errors.yaml, facts/valid.yaml"), ("w404", "in no fact file")):
        with pytest.raises(writer.WriteError, match=message):
            writer.apply_delta(pack_dir, {"format": writer.FORMAT, "changes": [
                {"op": "set", "kind": "work", "key": key, "slot": "year", "value": "1948"}]}, lay)
    with pytest.raises(writer.WriteError, match="file must be"):
        writer.apply_delta(pack_dir, {"format": writer.FORMAT, "changes": [
            {"op": "insert", "kind": "work", "key": "w9", "values": {"title": "Nieuw"}}]}, lay)


def test_a_pack_that_imports_is_checked_out_with_its_imports(work):
    """An import is a path relative to the pack: a work dir holds the imported packs at their places, each
    checked against its pin, so the copy compiles and the writer writes in it."""
    found = [(d, f) for d, f in FILES if (yaml.safe_load((d / "pack.yaml").read_text("utf-8")) or {}).get("imports")]
    if not found:
        pytest.skip("no example pack imports another")
    pack_dir, path = found[0]
    pack = writer.checkout(pack_dir, work)
    assert layout(pack).pack.meta["name"] == layout(pack_dir).pack.meta["name"]
    delta = delete_first(pack_dir, path, work)
    assert writer.main(["apply", str(pack), str(delta)]) == 0
    assert (pack / path.relative_to(pack_dir)).read_bytes() != path.read_bytes()


def test_a_checkout_refuses_an_import_that_is_not_its_pin(tmp_path, work):
    found = [d for d, _ in FILES if (yaml.safe_load((d / "pack.yaml").read_text("utf-8")) or {}).get("imports")]
    if not found:
        pytest.skip("no example pack imports another")
    copy = modules.copy_closure(found[0], tmp_path / "copy")
    _, imported = modules.closure(copy)
    # Any definition file of the imported pack: it need not have a schema (std-explain has questions only).
    changed = modules.definition_files(imported[0][1])[0]
    changed.write_text(changed.read_text("utf-8") + "# changed\n", "utf-8")
    with pytest.raises(ValueError, match="not the pinned"):
        writer.checkout(copy, work)
