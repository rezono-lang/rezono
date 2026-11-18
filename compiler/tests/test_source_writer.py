"""Independent expected rows/origins for the pure source-write planner (the writer's use of it: test_writer_sources.py)."""
import copy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_compiler import facts, source_writer as sw, sources, writer
from test_sources import fixture  # noqa: F401 (a pytest fixture)


def origin(n):
    return {"kind": "person", "name": "fixture-author", "position": f"register-{n}"}


def entry(table, values, n=1):
    return {"row": {"relation": table, "key": canonical_json(values)}, "sources": [origin(n)]}


BASE = [entry("alpha", ["a"]), entry("alpha__title", ["a", "Alpha"]), entry("alpha__size", ["a", 1])]
PROPOSAL = sw.ProposalSource("17", "p-17-42")


def inputs(root, changes, changed_origins, *, base_origins=None, files=None):
    files = files if files is not None else {"facts/data.yaml": (root / "facts/data.yaml").read_bytes()}
    pin = sw.VerifiedBasePin("example/model", "a" * 40, "packs/minimal",
        {n: sw.PinnedFile(b, sha256(b).hexdigest()) for n, b in files.items()})
    evidence = sw.OriginEvidence({"facts/data.yaml": tuple(BASE)} if base_origins is None else base_origins,
                                 {i: tuple(es) for i, es in changed_origins.items()})
    return writer.layout(root), {"format": writer.FORMAT, "changes": changes}, pin, PROPOSAL, evidence


def apply(files, changes):
    out = dict(files)
    for name, data in changes.items():
        if data is None:
            out.pop(name, None)
        else:
            out[name] = data
    return out


@pytest.mark.parametrize("change,added,expected", [
    ({"op": "set", "slot": "size", "value": 2}, [entry("alpha__size", ["a", 2], 2)],
     BASE[:2] + [entry("alpha__size", ["a", 2], 2)]),
    ({"op": "unset", "slot": "size"}, [], BASE[:2]),
    ({"op": "delete"}, [], []),
    ({"op": "insert", "key": "b", "values": {"title": "Beta", "size": 2}},
     [entry("alpha", ["b"], 2), entry("alpha__title", ["b", "Beta"], 2), entry("alpha__size", ["b", 2], 2)],
     BASE + [entry("alpha", ["b"], 2), entry("alpha__title", ["b", "Beta"], 2), entry("alpha__size", ["b", 2], 2)]),
])
def test_all_operations_have_explicit_origins_and_exact_byte_undo(fixture, change, added, expected):
    change = {"file": "facts/data.yaml", "kind": "alpha", "key": "a"} | change
    args = inputs(fixture, [change], {0: added})
    saved = copy.deepcopy(args[1:])
    result = sw.plan(*args)
    assert list(result.origins["facts/data.yaml"]) == sources.collected(expected)
    before = {n: p.content for n, p in args[2].files.items()}
    after = apply(before, result.files)
    assert apply(after, result.undo.restore(after)) == before
    assert result.undo.before["facts/data.sources.yaml"] is None
    assert args[1:] == saved
    assert (fixture / "facts/data.yaml").read_bytes() == before["facts/data.yaml"]


def test_same_value_is_touched_and_stale_fact_bytes_also_block_source_only_undo(fixture):
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "a", "slot": "size", "value": 1}],
                  {0: [entry("alpha__size", ["a", 1], 2)]})
    result = sw.plan(*args)
    assert "facts/data.yaml" not in result.files
    assert next(e for e in result.origins["facts/data.yaml"] if e["row"]["relation"] == "alpha__size")["sources"] == [origin(2)]
    after = apply({n: p.content for n, p in args[2].files.items()}, result.files)
    with pytest.raises(writer.WriteError, match="stale source undo"):
        result.undo.restore(after | {"facts/data.yaml": after["facts/data.yaml"] + b"# later\n"})


def test_multivalue_overlap_uses_the_supplied_origin_for_every_set_result(fixture):
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, size: [1, 2]}\n", encoding="utf-8")
    before = BASE[:2] + [entry("alpha__size", ["a", 1]), entry("alpha__size", ["a", 2], 3)]
    new = [entry("alpha__size", ["a", 2], 2), entry("alpha__size", ["a", 3], 2)]
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "a", "slot": "size", "value": [2, 3]}],
                  {0: new}, base_origins={"facts/data.yaml": tuple(before)})
    result = sw.plan(*args)
    assert list(result.origins["facts/data.yaml"]) == sources.collected(BASE[:2] + new)
    initial = {n: p.content for n, p in args[2].files.items()}
    assert apply(apply(initial, result.files), result.undo.restore(apply(initial, result.files))) == initial


def test_line_shift_is_pinned_as_transport_never_promoted_to_an_origin(fixture):
    new = [entry("alpha", ["0"], 2), entry("alpha__title", ["0", "Zero"], 2)]
    args = inputs(fixture, [{"op": "insert", "file": "facts/data.yaml", "kind": "alpha", "key": "0", "values": {"title": "Zero"}}], {0: new})
    result = sw.plan(*args)
    assert result.transport and all(p.commit == "a" * 40 and p.path == "packs/minimal/facts/data.yaml" and p.lines == (2,) for p in result.transport)
    assert result.files["facts/data.yaml"].decode().splitlines()[1].startswith("  - {id: '0'")
    assert all(s["kind"] == "person" for e in result.origins["facts/data.yaml"] for s in e["sources"])


@pytest.mark.parametrize("missing", ["base", "changed"])
def test_serialization_or_proposal_context_is_not_a_missing_real_origin_fallback(fixture, missing):
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "a", "slot": "size", "value": 2}],
                  {} if missing == "changed" else {0: [entry("alpha__size", ["a", 2], 2)]},
                  base_origins={} if missing == "base" else None)
    with pytest.raises((writer.WriteError, facts.LoadError)):
        sw.plan(*args)


@pytest.mark.parametrize("kind", ["pack", "proposal", "scenario"])
def test_transport_change_and_scenario_locators_cannot_pose_as_real_origins(fixture, kind):
    supplied = entry("alpha__size", ["a", 2], 2)
    supplied["sources"] = [{"kind": kind, "name": "17", "revision": "p-17-42", "position": "0"}]
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "a", "slot": "size", "value": 2}], {0: [supplied]})
    with pytest.raises(writer.WriteError, match="not a real origin"):
        sw.plan(*args)


def test_explicit_real_origins_and_existing_sidecar_bytes_are_preserved_on_undo(fixture):
    sidecar = b"# existing origins\r\n" + canonical_json({"rows": BASE}).encode() + b"\r\n"
    files = {"facts/data.yaml": (fixture / "facts/data.yaml").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"), "facts/data.sources.yaml": sidecar}
    args = inputs(fixture, [{"op": "unset", "kind": "alpha", "key": "a", "slot": "size"}], {}, files=files)
    result = sw.plan(*args)
    assert apply(apply(files, result.files), result.undo.restore(apply(files, result.files))) == files
    wrong = replace(args[4], base={"facts/data.yaml": tuple(e | {"sources": [origin(9)]} for e in BASE)})
    with pytest.raises(writer.WriteError, match="explicit base origins would be replaced"):
        sw.plan(*args[:4], wrong)


@pytest.mark.parametrize("damage", ["hash", "path", "commit", "proposal", "extra_delta", "extra_change"])
def test_bad_context_or_client_origin_authority_fails_closed(fixture, damage):
    lay, delta, base, proposal, evidence = inputs(fixture, [{"op": "unset", "kind": "alpha", "key": "a", "slot": "size"}], {})
    if damage == "hash": base = replace(base, files={"facts/data.yaml": sw.PinnedFile(b"wrong", "0" * 64)})
    if damage == "path": base = replace(base, pack_path="../other")
    if damage == "commit": base = replace(base, commit="main")
    if damage == "proposal": proposal = sw.ProposalSource("17", "p-18-42")
    if damage == "extra_delta": delta["reviewed"] = True
    if damage == "extra_change": delta["changes"][0]["origins"] = BASE
    with pytest.raises(writer.WriteError):
        sw.plan(lay, delta, base, proposal, evidence)


def test_planning_reads_no_files(fixture, monkeypatch):
    args = inputs(fixture, [{"op": "unset", "kind": "alpha", "key": "a", "slot": "size"}], {})
    def refused(*args, **kwargs):
        raise AssertionError("pure planner attempted IO")
    with monkeypatch.context() as m:
        m.setattr(Path, "read_text", refused)
        m.setattr(Path, "read_bytes", refused)
        result = sw.plan(*args)
    assert result.files


def test_multiple_steps_and_new_file_restore_both_original_absences(fixture):
    new = [entry("alpha", ["b"], 2), entry("alpha__title", ["b", "Beta"], 2), entry("alpha__size", ["b", 2], 2)]
    changes = [{"op": "insert", "file": "facts/new.yaml", "kind": "alpha", "key": "b", "values": {"title": "Beta", "size": 2}},
               {"op": "set", "kind": "alpha", "key": "b", "slot": "size", "value": 3}]
    args = inputs(fixture, changes, {0: new, 1: [entry("alpha__size", ["b", 3], 3)]})
    result = sw.plan(*args)
    assert list(result.origins["facts/new.yaml"]) == sources.collected(new[:2] + [entry("alpha__size", ["b", 3], 3)])
    initial = {n: p.content for n, p in args[2].files.items()}
    assert "facts/data.yaml" not in result.files
    assert "facts/data.sources.yaml" not in result.files
    assert result.undo.before["facts/new.yaml"] is None
    assert result.undo.before["facts/new.sources.yaml"] is None
    assert apply(apply(initial, result.files), result.undo.restore(apply(initial, result.files))) == initial


def test_unexplained_origin_rows_and_extra_step_inputs_are_rejected(fixture):
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "a", "slot": "size", "value": 2}],
                  {0: [entry("alpha__size", ["a", 1], 2)]})
    with pytest.raises(writer.WriteError, match="exactly the touched"):
        sw.plan(*args)
    extra = replace(args[4], changes={4: ()})
    with pytest.raises(writer.WriteError, match="no delta step"):
        sw.plan(*args[:4], extra)


def test_integer_identifiers_are_typed_before_matching_touched_rows(fixture):
    path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Alpha"]["attributes"]["id"]["range"] = "integer"
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: 7, title: Seven, size: 1}\n", encoding="utf-8")
    before = [entry("alpha", [7]), entry("alpha__title", [7, "Seven"]), entry("alpha__size", [7, 1])]
    new = [entry("alpha__size", [7, 2], 2)]
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "7", "slot": "size", "value": "2"}],
                  {0: new}, base_origins={"facts/data.yaml": tuple(before)})
    result = sw.plan(*args)
    assert list(result.origins["facts/data.yaml"]) == sources.collected(before[:2] + new)


def test_explicit_document_origins_keep_their_licence_hash_and_attribution(fixture):
    document = {"kind": "document", "name": "Example manual", "position": "section-2", "revision": "v2",
                "url": "https://docs.example.invalid/manual", "fragment_sha256": "a" * 64,
                "ownership": "third_party", "licence": "LicenseRef-fixture", "attribution": "Example author"}
    before = [e | {"sources": [document]} for e in BASE]
    files = {"facts/data.yaml": (fixture / "facts/data.yaml").read_bytes(),
             "facts/data.sources.yaml": canonical_json({"rows": before}).encode()}
    new = entry("alpha__size", ["a", 2]) | {"sources": [document | {"position": "section-3"}]}
    args = inputs(fixture, [{"op": "set", "kind": "alpha", "key": "a", "slot": "size", "value": 2}],
                  {0: [new]}, base_origins={"facts/data.yaml": tuple(before)}, files=files)
    result = sw.plan(*args)
    assert list(result.origins["facts/data.yaml"]) == sources.collected(before[:2] + [new])


@pytest.mark.parametrize("op", ["set", "unset"])
def test_nested_owned_rows_are_touched_but_parent_record_rows_are_not(fixture, op):
    path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Alpha"]["attributes"]["detail"] = {"range": "Detail", "inlined": True}
    schema["classes"]["Detail"] = {"attributes": {"sub": {"range": "Sub", "inlined": True}}}
    schema["classes"]["Sub"] = {"attributes": {"text": {}}}
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    labels = fixture / "labels/nl.yaml"
    labels.write_text(labels.read_text("utf-8") + "alpha.detail: Detail\ndetail: Detail\ndetail.sub: Sub\nsub: Sub\nsub.text: Text\n", encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, detail: {sub: {text: Old}}}\n", encoding="utf-8")
    child, sub = "a/alpha.detail", "a%2Falpha.detail/detail.sub"
    def nested(text, n):
        return [entry("alpha__detail", ["a", child], n), entry("detail", [child], n),
                entry("detail__sub", [child, sub], n), entry("sub", [sub], n), entry("sub__text", [sub, text], n)]
    before = BASE[:2] + nested("Old", 1)
    changed = nested("New", 2) if op == "set" else []
    change = {"op": op, "kind": "alpha", "key": "a", "slot": "detail"}
    if op == "set": change["value"] = {"sub": {"text": "New"}}
    result = sw.plan(*inputs(fixture, [change], {0: changed}, base_origins={"facts/data.yaml": tuple(before)}))
    assert list(result.origins["facts/data.yaml"]) == sources.collected(BASE[:2] + changed)


def test_ambiguous_inherited_duplicate_contributions_are_refused(fixture):
    path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Child"] = {"is_a": "Alpha"}
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    labels = fixture / "labels/nl.yaml"
    labels.write_text(labels.read_text("utf-8") + "child: Child\n", encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, size: 1}\nchild:\n  - {id: a, title: Alpha, size: 1}\n", encoding="utf-8")
    before = BASE + [entry("child", ["a"])]
    args = inputs(fixture, [{"op": "delete", "kind": "alpha", "key": "a"}], {}, base_origins={"facts/data.yaml": tuple(before)})
    with pytest.raises(writer.WriteError, match="ambiguous shared-row"):
        sw.plan(*args)
