"""The canonical writer on a pack with source companions (S25 step 5b): a delta changes a fact file and its
companion together, its undo gives both back byte for byte, and a written row without a real origin from the
caller is refused. A fact file without a companion is written exactly as in a pack without companions."""

import copy
import json
import shutil
from hashlib import sha256

import pytest
import yaml

from rede_canon import canonical_json
from rede_compiler import pack, source_writer as sw, sources, writer
from test_sources import DEFAULT, fixture  # noqa: F401 (a pytest fixture)

DATA, COMPANION = "facts/data.yaml", "facts/data.sources.yaml"
# A companion as an ingest writes it: a default, a record and a cell, with a comment and CRLF line ends.
HEAD = ('# made by an ingest\r\ndefault: {kind: git, name: example/model, revision: ' + "a" * 40
        + ', position: corpus/snapshot.json}\r\n')
RECORD = 'records:\r\n  - {of: {kind: alpha, id: a}, position: /entities/1}\r\n'
INGESTED = HEAD + RECORD + '  - {of: {kind: alpha, id: a, slot: size}, position: /entities/1/size}\r\n'
ENTITY = DEFAULT | {"position": "corpus/snapshot.json#/entities/1"}
CELL = DEFAULT | {"position": "corpus/snapshot.json#/entities/1/size"}
REGISTER = {"kind": "person", "name": "register", "position": "row-7"}
DECISION = {"kind": "person", "name": "board", "position": "minutes-12"}


def entry(table, values, source):
    return {"row": {"relation": table, "key": canonical_json(values)}, "sources": [source]}


BASE = [entry("alpha", ["a"], ENTITY), entry("alpha__title", ["a", "Alpha"], ENTITY), entry("alpha__size", ["a", 1], CELL)]
BETA = [entry("alpha", ["b"], DECISION), entry("alpha__title", ["b", "Beta"], DECISION), entry("alpha__size", ["b", 2], DECISION)]


def rows(*entries, end="\r\n"):
    """The exact rows as the writer adds them to a companion that keeps its form: one per line, at the end."""
    return "rows:" + end + "".join(f"  - {canonical_json(e)}{end}" for e in sources.collected(entries))


def canonical(entries):
    return canonical_json({"rows": sources.collected(entries)}) + "\n"


def delta(*changes, **top):
    return {"format": writer.FORMAT, **top, "changes": [{"kind": "alpha", "key": "a"} | c for c in changes]}


@pytest.fixture
def work():
    d = writer.work_dir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def checked_out(fixture, work):
    """The fixture pack with an ingested companion, in a work dir as a proposal job has it."""
    (fixture / COMPANION).write_bytes(INGESTED.encode("utf-8"))
    return writer.checkout(fixture, work)


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def read(root):
    return sources.read(pack.read(root), root)


@pytest.mark.parametrize("change,origin,expected,companion", [
    # A written row is an exact row at the end; the default, the selectors and the comment stay as they are.
    ({"op": "set", "slot": "size", "value": 2}, DECISION, BASE[:2] + [entry("alpha__size", ["a", 2], DECISION)],
     INGESTED + rows(entry("alpha__size", ["a", 2], DECISION))),
    ({"op": "set", "slot": "size", "value": 1}, DECISION, BASE[:2] + [entry("alpha__size", ["a", 1], DECISION)],
     INGESTED + rows(entry("alpha__size", ["a", 1], DECISION))),
    # A selector that names no cell or record any more goes, and `records` with its last one.
    ({"op": "unset", "slot": "size"}, None, BASE[:2], HEAD + RECORD),
    ({"op": "delete"}, None, [], HEAD),
    ({"op": "insert", "file": DATA, "key": "b", "values": {"title": "Beta", "size": 2}}, DECISION, BASE + BETA,
     INGESTED + rows(*BETA)),
])
def test_facts_and_companion_change_together_and_the_undo_gives_both_back(checked_out, change, origin, expected, companion):
    before = files(checked_out)
    texts, undo = writer.apply_delta(checked_out, delta(change), origins=origin and {0: {"sources": [origin]}})
    assert set(texts) == {DATA, COMPANION} and files(checked_out) == before  # nothing is written yet
    writer.write_files(checked_out, texts)
    assert read(checked_out) == sources.collected(expected)  # the compiler reads what the writer wrote
    assert texts[COMPANION] == companion  # an ingested companion keeps its form: the diff is what changed
    back, redo = writer.apply_delta(checked_out, undo, undo=True)
    writer.write_files(checked_out, back)
    assert files(checked_out) == before  # the comment, the selectors and the CRLF of the companion too
    again, _ = writer.apply_delta(checked_out, redo, undo=True)
    assert again == texts


def test_a_second_delta_on_a_companion_that_kept_its_form(checked_out):
    """The exact rows are one section at the end, written again per delta: a row a later delta removes or
    writes again leaves no stale entry, and each undo gives back the bytes of the step before."""
    first, _ = writer.apply_delta(checked_out, delta({"op": "set", "slot": "size", "value": 2}), origins={0: {"sources": [DECISION]}})
    writer.write_files(checked_out, first)
    one = files(checked_out)
    steps = delta({"op": "insert", "file": DATA, "key": "b", "values": {"title": "Beta", "size": 2}},
                  {"op": "set", "slot": "size", "value": 3}, {"op": "set", "slot": "title", "value": "Alfa"})
    second, undo = writer.apply_delta(checked_out, steps, origins={0: {"sources": [DECISION]}}, stated=PROPOSER)
    written = [entry("alpha__title", ["a", "Alfa"], STATED), entry("alpha__size", ["a", 3], STATED), *BETA]
    assert second[COMPANION] == INGESTED + rows(*written)
    writer.write_files(checked_out, second)
    assert read(checked_out) == sources.collected([BASE[0], *written])
    two = files(checked_out)
    # The cell goes with its exact row and its selector; the record's own row still has the selector's source.
    third, back = writer.apply_delta(checked_out, delta({"op": "unset", "slot": "size"}, {"op": "delete", "key": "b"}))
    assert third[COMPANION] == HEAD + RECORD + rows(written[0])
    writer.write_files(checked_out, third)
    assert read(checked_out) == sources.collected([BASE[0], written[0]])
    for delta_back, state in ((back, two), (undo, one)):
        writer.write_files(checked_out, writer.apply_delta(checked_out, delta_back, undo=True)[0])
        assert files(checked_out) == state


LF = INGESTED.replace("\r\n", "\n")


@pytest.mark.parametrize("ingested,change,kept", [
    # Its own line end, also where the last line has none; an item of more lines stays while its selector holds.
    (LF.rstrip("\n"), {"op": "set", "slot": "size", "value": 2}, LF + rows(entry("alpha__size", ["a", 2], DECISION), end="\n")),
    (LF.replace(", position: /entities/1}", ",\n     position: /entities/1}  # the record"), {"op": "unset", "slot": "size"},
     (HEAD + RECORD).replace("\r\n", "\n").replace(", position: /entities/1}", ",\n     position: /entities/1}  # the record")),
    (LF.replace("/size}\n", "/size}  # the cell\n"), {"op": "unset", "slot": "size"}, (HEAD + RECORD).replace("\r\n", "\n")),
    # A layout the writer does not edit line by line becomes the canonical rows form, as before:
    (canonical_json(yaml.safe_load(INGESTED)) + "\n", {"op": "set", "slot": "size", "value": 2}, None),  # one flow line
    (LF.replace(", position: /entities/1/size}", ",\n     position: /entities/1/size}"), {"op": "unset", "slot": "size"}, None),  # an item of two lines goes
    (LF.replace("  - {of: {kind: alpha, id: a, slot: size}, position: /entities/1/size}",
                "  - of: {kind: alpha, id: a, slot: size}\n    position: /entities/1/size"), {"op": "unset", "slot": "size"}, None),
    (LF.replace("records:", '"records":'), {"op": "delete"}, None),  # the last item goes, and its section is not a plain line
    ("rows: []\n" + LF, {"op": "set", "slot": "size", "value": 2}, None),  # exact rows before another section
    (LF + "rows: [" + canonical_json(entry("alpha__size", ["a", 1], REGISTER)) + "]\n", {"op": "set", "slot": "size", "value": 2},
     LF + rows(entry("alpha__size", ["a", 2], DECISION), end="\n")),  # exact rows at the end are written again
])
def test_a_companion_keeps_its_layout_or_becomes_the_canonical_rows_form(fixture, work, ingested, change, kept):
    (fixture / COMPANION).write_bytes(ingested.encode("utf-8"))
    checked_out = writer.checkout(fixture, work)
    before = files(checked_out)
    texts, undo = writer.apply_delta(checked_out, delta(change), origins=change["op"] == "set" and {0: {"sources": [DECISION]}})
    writer.write_files(checked_out, texts)
    expected = read(checked_out)
    assert expected == sources.collected({"set": BASE[:2] + [entry("alpha__size", ["a", 2], DECISION)], "unset": BASE[:2], "delete": []}[change["op"]])
    assert texts[COMPANION] == (canonical(expected) if kept is None else kept)
    writer.write_files(checked_out, writer.apply_delta(checked_out, undo, undo=True)[0])
    assert files(checked_out) == before


def test_cli_round_trip_with_origins(checked_out, tmp_path):
    before = files(checked_out)
    steps = delta({"op": "insert", "file": DATA, "key": "b", "values": {"title": "Beta"}},
                  {"op": "set", "slot": "title", "value": "Alfa"}, {"op": "unset", "slot": "size"})
    (tmp_path / "delta.json").write_text(json.dumps(steps))
    (tmp_path / "origins.json").write_text(json.dumps({"0": {"sources": [DECISION]}, "1": {"sources": [REGISTER], "reason": "alpha.renamed"}}))
    apply = ["apply", str(checked_out), str(tmp_path / "delta.json"), "--inverse", str(tmp_path / "undo.json")]
    assert writer.main(apply) == 1 and files(checked_out) == before  # no origins: refused, nothing written
    assert writer.main([*apply, "--origins", str(tmp_path / "origins.json")]) == 0
    assert read(checked_out) == sources.collected([
        entry("alpha", ["a"], ENTITY), entry("alpha__title", ["a", "Alfa"], REGISTER) | {"reason": "alpha.renamed"},
        entry("alpha", ["b"], DECISION), entry("alpha__title", ["b", "Beta"], DECISION)])
    assert writer.main(["apply", str(checked_out), str(tmp_path / "undo.json")]) == 1  # an undo's sources need --undo
    assert writer.main(["apply", str(checked_out), str(tmp_path / "undo.json"), "--undo"]) == 0
    assert files(checked_out) == before


def test_the_writer_and_the_planner_give_the_same_bytes(fixture):
    canonical = canonical_json({"rows": sources.collected(BASE)}) + "\n"
    (fixture / COMPANION).write_text(canonical, encoding="utf-8", newline="\n")
    steps = delta({"op": "set", "slot": "size", "value": 2}, {"op": "insert", "file": DATA, "key": "b", "values": {"title": "Beta"}})
    texts, _ = writer.apply_delta(fixture, steps, origins={0: {"sources": [DECISION]}, 1: {"sources": [REGISTER]}})
    pinned = {n: sw.PinnedFile(b, sha256(b).hexdigest()) for n in (DATA, COMPANION) for b in [(fixture / n).read_bytes()]}
    planned = sw.plan(writer.layout(fixture), steps, sw.VerifiedBasePin("example/model", "a" * 40, "packs/minimal", pinned),
                      sw.ProposalSource("17", "p-17-42"), sw.OriginEvidence({DATA: tuple(BASE)}, {
                          0: (entry("alpha__size", ["a", 2], DECISION),),
                          1: (entry("alpha", ["b"], REGISTER), entry("alpha__title", ["b", "Beta"], REGISTER))}))
    assert {n: t.encode("utf-8") for n, t in texts.items()} == dict(planned.files)


def test_a_fact_file_without_a_companion_is_written_as_in_a_pack_without_companions(fixture, monkeypatch):
    """The pilot's case on a pack whose other fact file has a companion: these rows keep file and line."""
    (fixture / "facts/other.yaml").write_text("alpha:\n  - {id: o, title: Other}\n", encoding="utf-8", newline="\n")
    steps = delta({"op": "set", "slot": "title", "value": "Alpha (pilot)"}, {"op": "insert", "file": "facts/new.yaml", "key": "n", "values": {"title": "New"}})
    with monkeypatch.context() as m:  # without companions the source writer is not even loaded
        m.setattr(sw, "Companions", None)
        plain = writer.apply_delta(fixture, steps)
    (fixture / "facts/other.sources.yaml").write_text(yaml.safe_dump({"default": DEFAULT}), encoding="utf-8")
    assert writer.apply_delta(fixture, steps) == plain
    assert set(plain[0]) == {DATA, "facts/new.yaml"} and "sources" not in plain[1]
    with pytest.raises(writer.WriteError, match="origin input for change 0 is not used"):
        writer.apply_delta(fixture, steps, origins={0: {"sources": [DECISION]}})


@pytest.mark.parametrize("change,origins,message", [
    ({"op": "set", "slot": "size", "value": 2}, None, "need their real origin"),
    ({"op": "insert", "file": DATA, "key": "b", "values": {"title": "Beta"}}, None, "need their real origin"),
    ({"op": "set", "slot": "size", "value": 2}, {0: {"sources": []}}, "nonempty sources"),
    ({"op": "set", "slot": "size", "value": 2}, {0: {"sources": [{"kind": "person", "name": "board"}]}}, "a source needs kind, name and position"),
    ({"op": "set", "slot": "size", "value": 2}, {0: [DECISION]}, "an origin is"),
    ({"op": "set", "slot": "size", "value": 2}, {0: {"sources": [DECISION], "row": {}}}, "an origin is"),
    ({"op": "set", "slot": "size", "value": 2}, {1: {"sources": [DECISION]}}, "names no delta step"),
    ({"op": "set", "slot": "size", "value": 2}, {"0": {"sources": [DECISION]}}, "names no delta step"),
    ({"op": "unset", "slot": "size"}, {0: {"sources": [DECISION]}}, "is not used"),
    ({"op": "set", "slot": "size", "value": 2, "sources": [DECISION]}, {0: {"sources": [DECISION]}}, "a change cannot supply origin"),
] + [({"op": "set", "slot": "size", "value": 2},
      {0: {"sources": [{"kind": kind, "name": "17", "revision": "p-17-42", "position": "0"}]}}, "not a real origin")
     for kind in ("pack", "proposal", "scenario")])
def test_a_written_row_without_a_real_origin_from_the_caller_is_refused(checked_out, change, origins, message):
    before = files(checked_out)
    with pytest.raises(writer.WriteError, match=message):
        writer.apply_delta(checked_out, delta(change), origins=origins)
    assert files(checked_out) == before


def test_a_delta_cannot_carry_origins_and_an_undo_only_fits_the_bytes_it_was_made_for(checked_out):
    change = {"op": "set", "slot": "size", "value": 2}
    texts, undo = writer.apply_delta(checked_out, delta(change), origins={0: {"sources": [DECISION]}})
    assert [set(e) for e in undo["sources"]] == [sw.RESTORE_KEYS]
    with pytest.raises(writer.WriteError, match="a delta cannot supply origins"):  # also before it is written
        writer.apply_delta(checked_out, undo)
    with pytest.raises(writer.WriteError, match="stale source undo"):  # the pack is not in the state the undo left
        writer.apply_delta(checked_out, undo, undo=True)
    writer.write_files(checked_out, texts)
    after = files(checked_out)
    for damage, message in (("changes", "do not give back the facts"), ("entry", "'sources' entry has"),
                            ("unknown", "need their real origin"), ("twice", "'sources' entry has")):
        bad = copy.deepcopy(undo)
        if damage == "changes":  # the companion would go back beside facts it does not describe
            bad["changes"][0] = {"op": "set", "file": DATA, "kind": "alpha", "key": "a", "slot": "size", "value": 3}
        if damage == "entry":
            bad["sources"][0]["reviewed"] = "yes"
        if damage == "unknown":
            bad["sources"][0]["file"] = "facts/other.sources.yaml"
        if damage == "twice":
            bad["sources"] *= 2
        with pytest.raises(writer.WriteError, match=message):
            writer.apply_delta(checked_out, bad, undo=True)
    for name, more in ((DATA, "# later\n"), (COMPANION, "\n")):
        (checked_out / name).write_bytes(after[name] + more.encode())
        with pytest.raises(writer.WriteError, match="stale source undo"):
            writer.apply_delta(checked_out, undo, undo=True)
        (checked_out / name).write_bytes(after[name])
    assert files(checked_out) == after
    # Without its sources the undo is a delta like any other: the row it writes back needs its origin again.
    plain = {k: v for k, v in undo.items() if k != "sources"}
    with pytest.raises(writer.WriteError, match="need their real origin"):
        writer.apply_delta(checked_out, plain)
    back, _ = writer.apply_delta(checked_out, plain, origins={0: {"sources": [CELL]}})
    writer.write_files(checked_out, back)
    assert read(checked_out) == sources.collected(BASE)


@pytest.mark.parametrize("kind", ["pack", "proposal", "scenario"])
def test_a_companion_that_holds_a_storage_or_change_locator_is_refused(checked_out, kind):
    locator = {"kind": kind, "name": DATA, "revision": "p-17-42", "position": "2"}
    (checked_out / COMPANION).write_text(yaml.safe_dump({"default": locator}), encoding="utf-8")
    with pytest.raises(writer.WriteError, match="not a real origin"):
        writer.apply_delta(checked_out, delta({"op": "unset", "slot": "size"}))


def test_a_row_two_records_give_is_refused(checked_out):
    path = checked_out / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Child"] = {"is_a": "Alpha"}
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    labels = checked_out / "labels/nl.yaml"
    labels.write_text(labels.read_text("utf-8") + "child: Child\n", encoding="utf-8")
    (checked_out / DATA).write_text("alpha:\n  - {id: a, title: Alpha, size: 1}\nchild:\n  - {id: a, title: Alpha, size: 1}\n", encoding="utf-8")
    with pytest.raises(writer.WriteError, match="ambiguous shared-row"):
        writer.apply_delta(checked_out, delta({"op": "delete"}))


def test_write_files_never_leaves_a_companion_behind_its_facts(checked_out):
    before = files(checked_out)
    texts, _ = writer.apply_delta(checked_out, delta({"op": "unset", "slot": "size"}))
    with pytest.raises(writer.WriteError, match="its source companion must be written with it"):
        writer.write_files(checked_out, {DATA: texts[DATA]})
    assert files(checked_out) == before
    # What a caller does to try a value and go back (the sweep): keep the originals of every text, write, restore.
    originals = {f: writer.read_fact_file(checked_out, f) for f in texts}
    writer.write_files(checked_out, texts)
    assert files(checked_out) != before
    writer.write_files(checked_out, originals)
    assert files(checked_out) == before
    writer.write_files(checked_out, {DATA: originals[DATA]})  # unchanged facts need no companion
    for outside in ("facts/data.sources.yml", "facts/../pack.yaml", "schema/data.sources.yaml"):
        with pytest.raises(writer.WriteError, match="file must be facts/<name>.yaml"):
            writer.write_files(checked_out, {outside: ""})


PROPOSER = sw.stated("user-123", "2026-11-10T21:03:11Z")
STATED = {"kind": "person", "name": "user-123", "position": "2026-11-10T21:03:11Z"}


def test_who_states_a_delta_is_the_origin_of_every_row_it_writes(checked_out):
    """RV-M17: the propose path names the proposer once; a step with an origin of its own keeps that one."""
    assert PROPOSER == {"sources": [STATED]}
    before = files(checked_out)
    steps = delta({"op": "set", "slot": "size", "value": 2}, {"op": "insert", "file": DATA, "key": "b", "values": {"title": "Beta"}},
                  {"op": "set", "slot": "title", "value": "Alfa"})
    texts, undo = writer.apply_delta(checked_out, steps, origins={1: {"sources": [DECISION]}}, stated=PROPOSER)
    assert files(checked_out) == before
    writer.write_files(checked_out, texts)
    assert read(checked_out) == sources.collected([
        entry("alpha", ["a"], ENTITY), entry("alpha__title", ["a", "Alfa"], STATED), entry("alpha__size", ["a", 2], STATED),
        entry("alpha", ["b"], DECISION), entry("alpha__title", ["b", "Beta"], DECISION)])
    back, _ = writer.apply_delta(checked_out, undo, undo=True)
    writer.write_files(checked_out, back)
    assert files(checked_out) == before
    # It is no step's own origin: a delta that writes no row needs none, and none is "not used".
    removed, _ = writer.apply_delta(checked_out, delta({"op": "unset", "slot": "size"}), stated=PROPOSER)
    assert removed == writer.apply_delta(checked_out, delta({"op": "unset", "slot": "size"}))[0]


def test_a_fact_file_without_a_companion_takes_nothing_from_who_states_the_delta(fixture):
    (fixture / "facts/other.sources.yaml").write_text(yaml.safe_dump({"default": DEFAULT}), encoding="utf-8")
    (fixture / "facts/other.yaml").write_text("alpha:\n  - {id: o, title: Other}\n", encoding="utf-8", newline="\n")
    steps = delta({"op": "set", "slot": "title", "value": "Alpha (pilot)"})
    assert writer.apply_delta(fixture, steps, stated=PROPOSER) == writer.apply_delta(fixture, steps)


@pytest.mark.parametrize("stated,message", [
    ([STATED], "an origin is"),
    ({"sources": [STATED], "row": {}}, "an origin is"),
    ({"sources": []}, "nonempty sources"),
] + [({"sources": [{"kind": kind, "name": "17", "revision": "p-17-42", "position": "0"}]}, "not a real origin")
     for kind in ("pack", "proposal", "scenario")])
def test_who_states_a_delta_is_held_to_the_rules_of_an_origin(checked_out, stated, message):
    before = files(checked_out)
    with pytest.raises(writer.WriteError, match=message):
        writer.apply_delta(checked_out, delta({"op": "set", "slot": "size", "value": 2}), stated=stated)
    assert files(checked_out) == before


@pytest.mark.parametrize("who,at,message", [(who, "2026-11-10T21:03:11Z", "a plain identifier")
                                            for who in ("", "Anna Jansen", "anna@x.test", "u1\nu2", "u1\n", "-u", "u" * 129, None)]
                         + [("user-123", at, "a real UTC instant")
                            for at in ("", "2026-11-10T21:03:11", "2026-11-10 21:03:11Z", "2026-13-10T21:03:11Z",
                                       "2026-11-10T24:03:11Z", "2026-11-10T21:03:11.5Z", "2026-11-10T21:03:11Z\n",
                                       "2026-11-10T21:03:11+01:00", None)])
def test_who_states_is_a_plain_identifier_at_a_real_instant(who, at, message):
    with pytest.raises(writer.WriteError, match=message):
        sw.stated(who, at)
