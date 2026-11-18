"""Every example pack through the batch backend and the publisher (needs the compiler and DuckDB).

Generic: no pack is named. A pack with a red check is refused and nothing is written; a green pack is
published, its complete snapshots hold every derived row, every witness concludes a published row, and
publishing twice gives the same bytes, also in another process with another hash seed, time zone,
locale and working directory. A pack with expected/published/ holds a publication made earlier in CI
(regen-goldens); it is made again from its manifest and compared byte for byte.
"""

import dataclasses
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, kept, publish, store  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PACKS = sorted(p.parent for p in (ROOT / "examples").rglob("pack.yaml")
               if "expected" not in p.parts and (p.parent / "facts").is_dir())
ROLES = {"checker": "complete", "viewer": "may_read", "propose": "may_read"}


def object_bytes(s, role, name, mid="m-1"):
    return s.get(publish.role_objects(s, "minimal", mid, role)[name])


def run(pack_dir, tmp):
    """(epoch, store, manifest, refusal): a refused epoch has no manifest, and the refusal keeps its reason."""
    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    s = store.FileStore(tmp)
    try:
        return e, s, publish.publish(e, s, ROLES), ""
    except publish.Blocked as refused:
        assert s.list("") == [], "a refused epoch writes nothing"
        return e, s, None, str(refused)


def test_the_definition_hash_covers_every_file_the_compiler_reads(tmp_path):
    """Audit 07-11 (C1/C3): a calculation or a sweep is definition, so changing only one of them gives
    another definition_sha256, and with it another bundle key; facts do not change it."""
    d = Path(shutil.copytree(ROOT / "compiler" / "tests" / "fixtures" / "calc", tmp_path / "calc"))
    before = batch.definition_sha256(d)
    calc = d / "calc" / "example.yaml"
    calc.write_text(calc.read_text() + "\n")
    after_calc = batch.definition_sha256(d)
    (d / "sweeps.yaml").write_text("# a sweep file\n")
    after_sweep = batch.definition_sha256(d)
    (d / "facts").mkdir(exist_ok=True)
    (d / "facts" / "rows.yaml").write_text("# rows are data\n")
    assert len({before, after_calc, after_sweep}) == 3
    assert batch.definition_sha256(d) == after_sweep


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.relative_to(ROOT / "examples").as_posix())
def test_publish(pack_dir, tmp_path):
    e, s, m, refused = run(pack_dir, tmp_path / "a")
    if m is None:
        assert any(c["status"] == "red" for c in e.checks), f"refused without a red check: {refused}"
        return
    assert all(c["status"] != "red" for c in m["checks"])
    complete = {x["relation"]: x for x in m["snapshots"] if x["role"] == "checker"}
    assert set(complete) == set(e.rows)
    rows = {rel: {json.dumps(r["key"], separators=(",", ":"))
                  for r in json.loads(s.get(x["uri"].removeprefix("s3://rezono/")))}
            for rel, x in complete.items()}
    for w in json.loads(s.get(publish.role_objects(s, e.pack, "m-1", "checker")["witnesses.json"]))["witnesses"]:
        assert w["conclusion"]["key"] in rows[w["conclusion"]["relation"]]
    # A filtered role that the pack's own access rules name reads rows (an empty snapshot set means the rules miss it).
    named = {r[0] for r in e.rows.get("may_read", ())}
    for role in sorted(r for r, mode in ROLES.items() if mode == "may_read" and r in named):
        assert any(json.loads(s.get(x["uri"].removeprefix("s3://rezono/")))
                   for x in m["snapshots"] if x["role"] == role), f"{role} reads nothing"
    _, again, _, _ = run(pack_dir, tmp_path / "b")
    assert again.list("") == s.list("")
    assert all(again.get(k) == s.get(k) for k in s.list(""))
    assert {c["file"] for c in m["compiled"]} >= {"bundle/schema-bundle.json"}


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.relative_to(ROOT / "examples").as_posix())
def test_a_publication_is_made_again_byte_for_byte(pack_dir, tmp_path):
    """Publish once here, then again from the same inputs in a fresh process whose surroundings differ:
    every file, the archived bundle and rule IR included, must be the same bytes."""
    e, old, m, _ = run(pack_dir, tmp_path / "old")
    if m is None:
        return
    env = os.environ | {"PYTHONHASHSEED": "4242", "TZ": "Pacific/Kiritimati", "LC_ALL": "C", "LANG": "C"}
    roles = [a for r, mode in sorted(ROLES.items()) for a in ("--role", f"{r}={mode}")]
    subprocess.run([sys.executable, "-m", "rezono_publisher", str(pack_dir), "--store", f"file://{tmp_path / 'new'}",
                    *roles, "--epoch", "1", "--knowledge-time", "2026-01-01T00:00:00Z", "--source", "rules=test"],
                   check=True, env=env, cwd=tmp_path, capture_output=True)
    new = store.FileStore(tmp_path / "new")
    assert new.list("") == old.list("")
    assert [k for k in old.list("") if new.get(k) != old.get(k)] == []


# Correctness blocks, on the compiler's own neutral test pack with facts and rules added in a temp dir.
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
ZERO = "// @invariant\n.decl zero_size(a: symbol)\nzero_size(a) :- alpha__size(a, 0).\n"


def pack_with(tmp, facts, rules="", schema=lambda text: text):
    d = tmp / "pack"
    shutil.copytree(MINIMAL, d)
    (d / "facts").mkdir()
    for name, text in facts.items():
        (d / "facts" / name).write_text(text, encoding="utf-8")
    if rules:
        (d / "rules").mkdir()
        (d / "rules" / "checks.dl").write_text(rules, encoding="utf-8")
    p = d / "schema" / "minimal.yaml"
    p.write_text(schema(p.read_text(encoding="utf-8")), encoding="utf-8")
    return d


def publish_pack(d, tmp):
    e = batch.epoch(d, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    return e, publish.publish(e, store.FileStore(tmp / "store"), ROLES)


def alpha(*rows):
    return "alpha:\n" + "".join(f"  - {{id: {i}, title: t, size: {s}}}\n" for i, s in rows)


def test_an_invariant_with_rows_blocks(tmp_path):
    e, m = publish_pack(pack_with(tmp_path / "ok", {"a.yaml": alpha(("a1", 1))}, ZERO), tmp_path / "ok")
    assert {"name": "zero_size", "status": "green", "violations": 0} in m["checks"]
    with pytest.raises(publish.Blocked, match="zero_size"):
        publish_pack(pack_with(tmp_path / "red", {"a.yaml": alpha(("a1", 0))}, ZERO), tmp_path / "red")


def test_a_key_in_a_relation_and_in_the_relation_it_closes_blocks(tmp_path):
    """`// @closes`: the compiler adds the invariant, so the publisher stops as on any other."""
    closes = (".decl wide(a: symbol, s: number)\nwide(a, s) :- alpha__size(a, s), s >= 4.\n"
              "// @closes wide\n.decl narrow(a: symbol)\nnarrow(a) :- alpha__size(a, s), s < 5.\n")
    e, m = publish_pack(pack_with(tmp_path / "ok", {"a.yaml": alpha(("a1", 1), ("a2", 7))}, closes), tmp_path / "ok")
    assert {"name": "narrow_closes_wide", "status": "green", "violations": 0} in m["checks"]
    with pytest.raises(publish.Blocked, match="narrow_closes_wide"):
        publish_pack(pack_with(tmp_path / "red", {"a.yaml": alpha(("a1", 4))}, closes), tmp_path / "red")


@pytest.mark.parametrize("files", [
    {"a.yaml": alpha(("a1", 1), ("a1", 2))},              # twice in one file
    {"a.yaml": alpha(("a1", 1)), "b.yaml": alpha(("a1", 2))},  # once in each of two files
], ids=["one-file", "two-files"])
def test_a_duplicate_id_blocks(tmp_path, files):
    with pytest.raises(publish.Blocked, match="identification"):
        publish_pack(pack_with(tmp_path, files), tmp_path)


def test_an_invariant_nothing_checks_blocks(tmp_path):
    declared = lambda text: text.replace("annotations:\n  layer: facts", "annotations:\n  layer: facts\n  invariants: total")
    with pytest.raises(publish.Blocked, match="invariants"):
        publish_pack(pack_with(tmp_path, {"a.yaml": alpha(("a1", 1))}, schema=declared), tmp_path)


# A named outcome without a row for an element, or with two states, blocks.
SIZING = """// @outcome alpha
.decl sizing(a: symbol, state: symbol, reason: symbol)
sizing(a, "unknown", "small") :- alpha__size(a, s), s < 2.
"""
KNOWN = 'sizing(a, "known", "") :- alpha__size(a, s), s >= 2.\n'
TWICE = 'sizing(a, "not_applicable", "small") :- alpha__size(a, s), s < 2.\n'


def outcome_pack(tmp, rules):
    d = pack_with(tmp, {"a.yaml": alpha(("a1", 1), ("a2", 3))}, rules)
    with (d / "messages" / "nl.mf2").open("a", encoding="utf-8") as f:
        f.write("reason.small = {{Te klein om te weten.}}\n")
    return d


def test_a_complete_outcome_publishes(tmp_path):
    e, m = publish_pack(outcome_pack(tmp_path / "pack", SIZING + KNOWN), tmp_path)
    assert {"name": "sizing__total", "status": "green", "violations": 0} in m["checks"]
    assert {"name": "sizing__state", "status": "green", "violations": 0} in m["checks"]
    assert sorted(e.rows["sizing"]) == [("a1", "unknown", "small"), ("a2", "known", "")]


@pytest.mark.parametrize("rules, check", [(SIZING, "sizing__total"), (SIZING + KNOWN + TWICE, "sizing__state")],
                         ids=["an-element-without-a-row", "two-states"])
def test_an_incomplete_outcome_blocks(tmp_path, rules, check):
    with pytest.raises(publish.Blocked, match=check):
        publish_pack(outcome_pack(tmp_path / "pack", rules), tmp_path)


# A counter that reaches its bound blocks as a red check, `<relation>__exhausted`.
# The count of an element goes up to its size, and the bound stops it at 3.
COUNTER = """.decl depth(a: symbol, n: number)
depth(a, 0) :- alpha(a).
depth(a, m) :- depth(a, n), n < 3, alpha__size(a, s), n < s, m = n + 1.
"""


def test_a_counter_at_its_bound_blocks_with_its_check_and_one_within_it_publishes(tmp_path):
    e, m = publish_pack(pack_with(tmp_path / "ok", {"a.yaml": alpha(("a1", 3))}, COUNTER), tmp_path / "ok")
    assert {"name": "depth__exhausted", "status": "green", "violations": 0} in m["checks"]
    assert sorted(e.rows["depth"]) == [("a1", "0"), ("a1", "1"), ("a1", "2"), ("a1", "3")]
    # a1 would count on to 4: the epoch is made without a traceback, with the red check that names the view
    e, s, m, refused = run(pack_with(tmp_path / "red", {"a.yaml": alpha(("a1", 5), ("a2", 1))}, COUNTER), tmp_path / "s")
    assert m is None and refused == "depth__exhausted: 1"
    assert {"name": "depth__exhausted", "status": "red", "violations": 1} in e.checks


# A kept publication (rezono_publisher.kept): made in CI once, kept in Git, made again from its manifest.
PUBLISHED = [p for p in PACKS if kept.kept_dir(p).is_dir()]
# Those that hold one now (a pack that joins has none until regen-goldens makes it).
KEPT = [p for p in PUBLISHED if kept.manifests(store.FileStore(kept.kept_dir(p)))]
ids = lambda p: p.relative_to(ROOT / "examples").as_posix()


@pytest.mark.parametrize("pack_dir", PUBLISHED, ids=ids)
def test_a_kept_publication_is_made_again_byte_for_byte(pack_dir):
    """With the code, locks and pack it was made with (its archive), in a fresh virtualenv."""
    assert kept.check(pack_dir) == []


def kept_anew(tmp, source):
    """A kept publication of `source` made now, with this code (a v2 build record), from a copy of the pack
    with every pack it imports, laid out as in the repository so the imports resolve (modules.copy_closure)."""
    from rezono_compiler import modules

    pack = modules.copy_closure(source, tmp / "src")
    kept.kept_dir(pack).mkdir(parents=True)
    kept.make(pack, {"checker": "complete", "viewer": "may_read"})
    return pack


def imports(p):
    return bool((yaml.safe_load((p / "pack.yaml").read_text(encoding="utf-8")) or {}).get("imports"))


@pytest.fixture(scope="module")
def v2_source(tmp_path_factory):
    """A kept publication made now, with this code: a v2 build record (rezono_publisher.kept)."""
    if not KEPT:
        pytest.skip("no kept publication to take a pack from")
    return kept_anew(tmp_path_factory.mktemp("v2"), KEPT[0])


@pytest.fixture(scope="module")
def v2_imports(tmp_path_factory):
    """The same for a pack that imports other packs: its archive carries them, pinned."""
    found = [p for p in PACKS if imports(p)]
    if not found:
        pytest.skip("no example pack imports another")
    return kept_anew(tmp_path_factory.mktemp("v2-imports"), found[0])


def _forge(tmp_path, source, change, pin=True):
    """A copy of the kept publication of `source` whose archive `change` alters; `pin` also updates the
    archive digest, as someone who replaces an archive would."""
    import io
    import tarfile

    pack = tmp_path / "pack"
    shutil.copytree(kept.kept_dir(source), kept.kept_dir(pack))
    shutil.copytree(kept.source_dir(source), kept.source_dir(pack))
    for tar in kept.source_dir(pack).glob("*.tar.gz"):
        with tarfile.open(tar) as t:
            members = [(m, t.extractfile(m).read() if m.isreg() else b"") for m in t.getmembers()]
        members = change(members)
        with tarfile.open(tar, "w:gz") as t:
            for m, data in members:
                m.size = len(data) if m.isreg() else 0
                t.addfile(m, io.BytesIO(data) if m.isreg() else None)
        if pin:
            kept.digest_path(tar).write_text(kept.digest_line(tar, tar.read_bytes()), "utf-8")
    return pack


def _edit(name_test, edit):
    return lambda members: [(m, edit(data) if name_test(m.name) else data) for m, data in members]


def _extra(name, link=False):
    import tarfile

    def change(members):
        m = tarfile.TarInfo(name)
        if link:
            m.type, m.linkname = tarfile.SYMTYPE, "../../etc/passwd"
        return members + [(m, b"print('ran')\n")]
    return change


def _record(source):
    old = store.FileStore(kept.kept_dir(source))
    m = json.loads(old.get(kept.manifests(old)[0]))
    return json.loads(old.get(key(m["build"]["uri"])))


def _forged_fingerprint(source):
    """Other publisher code whose build record would still name the old publisher hash: the attack a
    replay alone cannot see, because the forged code reports the recorded fingerprint itself."""
    claimed = _record(source)["publisher"]
    old = 'tree_sha256(Path(__file__).parent, {".py"})'

    def forge(d):
        assert old.encode() in d, "the archived batch.py computes the publisher hash"
        return d.replace(old.encode(), repr(claimed).encode()) + b"\nFORGED = True\n"
    return _edit(lambda n: n == "edge/publisher/rezono_publisher/batch.py", forge)


# name: (change of the archive, archive digest updated too, what a v1 refusal names, what a v2 one names)
def _fact(name: str) -> bool:
    """A fact file of the pack, wherever the pack sits under pack/ (deeper when it imports other packs)."""
    return name.startswith("pack/") and "/facts/" in name


FORGERIES = {
    "a pack file": (lambda s: _edit(_fact, lambda d: d + b"# one more line\n"),
                    True, "is not the file", "archived pack"),
    "the archive bytes": (lambda s: _edit(_fact, lambda d: d + b"# more\n"),
                          False, "archive digest", "archive digest"),
    "a forged fingerprint": (_forged_fingerprint, True, "is not the file", "archived publisher"),
    # pyproject.toml decides what is installed: here the publisher from a module beside the locks.
    "an installation redirect": (lambda s: _edit(lambda n: n == "edge/publisher/pyproject.toml",
                                                 lambda d: d + b'\n[tool.setuptools.package-dir]\nrezono_publisher = "../../requirements"\n'),
                                 True, "is not the file", "archived install"),
    "a module beside the locks": (lambda s: _extra("requirements/rezono_publisher.py"), True, "is not the file", "not allowed"),
    "a module outside the allowed set": (lambda s: _extra("sitecustomize.py"), True, "not allowed", "not allowed"),
    "a file the code hashes skip": (lambda s: _extra("edge/publisher/rezono_publisher/_speedups.so"), True, "not allowed", "not allowed"),
    "a link": (lambda s: _extra("pack/facts/link.yaml", link=True), True, "not allowed", "not allowed"),
    "a path out of the tree": (lambda s: _extra("pack/../../escape.py"), True, "not allowed", "not allowed"),
}


def _nothing_runs(monkeypatch):
    def refuse(*a, **k):
        if a and a[0][:2] == ["git", "-C"]:  # reading the repository's own history is no execution
            return real(*a, **k)
        raise AssertionError(f"ran {a[0] if a else k} from a forged archive")

    real = subprocess.run
    monkeypatch.setattr(kept.subprocess, "run", refuse)


@pytest.mark.parametrize("forgery", list(FORGERIES))
def test_a_forged_v1_archive_is_refused_before_anything_runs(tmp_path, monkeypatch, forgery):
    """A v1 archive (the kept publications made at the commit in kept.V1_SOURCE): every member must be
    the file at its path in that commit, checked by the current code before anything from it runs."""
    if not KEPT:
        pytest.skip("no kept publication")
    source = KEPT[0]
    assert "format" not in _record(source), "the kept publications are v1, history"
    change, pin, named, _ = FORGERIES[forgery]
    pack = _forge(tmp_path, source, change(source), pin)
    where = kept.pack_path
    monkeypatch.setattr(kept, "pack_path", lambda p: where(source) if Path(p) == pack else where(p))
    _nothing_runs(monkeypatch)
    refused = kept.check(pack)
    assert any(named in r for r in refused), refused
    assert not (tmp_path / "escape.py").exists()


@pytest.mark.parametrize("forgery", list(FORGERIES))
def test_a_forged_v2_archive_is_refused_before_anything_runs(tmp_path, monkeypatch, v2_source, forgery):
    """A v2 archive: its build record names the hash of every member that can change what is installed
    or run, pyproject.toml included; archived code cannot vouch for itself."""
    assert _record(v2_source)["format"] == kept.FORMAT
    change, pin, _, named = FORGERIES[forgery]
    pack = _forge(tmp_path, v2_source, change(v2_source), pin)
    _nothing_runs(monkeypatch)
    refused = kept.check(pack)
    assert any(named in r for r in refused), refused


def test_an_unforged_v2_archive_passes_the_check(tmp_path, v2_source, v2_imports):
    for n, source in enumerate((v2_source, v2_imports)):
        pack = _forge(tmp_path / str(n), source, lambda members: members)
        s = store.FileStore(kept.kept_dir(pack))
        assert kept.verify(pack, s, kept.manifests(s)[0], tmp_path / str(n) / "tree") == []


def _members(source):
    import tarfile

    tar = next(kept.source_dir(source).glob("*.tar.gz"))
    with tarfile.open(tar) as t:
        return [m.name for m in t.getmembers()]


def test_an_archive_carries_the_packs_its_pack_imports(v2_imports):
    """Each imported pack's definition files, at their place relative to the pack (pinned imports)."""
    from rezono_compiler import modules

    names = _members(v2_imports)
    base, found = modules.closure(v2_imports)
    for _, d in found:
        for f in modules.definition_files(d):
            assert f"pack/{f.relative_to(base).as_posix()}" in names
    at = Path(os.path.abspath(v2_imports)).relative_to(base).as_posix()
    assert f"pack/{at}/pack.yaml" in names and "pack/pack.yaml" not in names


IMPORT_FORGERIES = {
    # An imported pack whose files no longer hash to the pin in its importer's pack.yaml.
    # Any definition file of it: an imported pack need not have a schema (std-explain has questions only).
    "an imported pack file": (lambda n: n.startswith("pack/") and "/facts/" not in n and n.endswith(".yaml"),
                              "not the pinned"),
    # A file under pack/ that is neither the pack's nor a definition file of a pack it imports.
    "a file beside the packs": (None, "neither the pack's"),
}


@pytest.mark.parametrize("forgery", list(IMPORT_FORGERIES))
def test_a_forged_import_is_refused_before_anything_runs(tmp_path, monkeypatch, v2_imports, forgery):
    from rezono_compiler import modules

    base, found = modules.closure(v2_imports)
    imported = {f"pack/{d.relative_to(base).as_posix()}/" for _, d in found}
    which, named = IMPORT_FORGERIES[forgery]
    if which:
        hit = []
        change = _edit(lambda n: bool(which(n) and any(n.startswith(i) for i in imported)) and (hit.append(n) or True),
                       lambda d: d + b"# forged\n")
    else:
        change = _extra("pack/stray/notes.yaml")
    pack = _forge(tmp_path, v2_imports, change)
    assert not which or hit, "not vacuous: the forgery changed a file of an imported pack"
    _nothing_runs(monkeypatch)
    refused = kept.check(pack)
    assert any(named in r for r in refused), refused


@pytest.mark.xfail(strict=True, reason="kept replay refuses packs importing theories with views.yaml. The subsidy example declares its theory mapping at the main pack root. Existing archive boundary tests require refusal before parsing or executing archived code, so enabling replay needs a specified and independently verified mapping boundary.")
def test_a_kept_publication_with_imports_is_made_again_byte_for_byte(v2_imports):
    """The replay resolves the imports inside the archive, with the archived code."""
    assert kept.check(v2_imports) == []


def test_a_v1_archive_without_its_commit_is_refused(tmp_path, monkeypatch):
    """A clone without the source commit (shallow, or another history) cannot check a v1 archive: refused."""
    if not KEPT:
        pytest.skip("no kept publication")
    record = kept.manifests(store.FileStore(kept.kept_dir(KEPT[0])))
    sha = json.loads(store.FileStore(kept.kept_dir(KEPT[0])).get(record[0]))["build"]["sha256"]
    monkeypatch.setitem(kept.V1_SOURCE, sha, "0" * 40)
    _nothing_runs(monkeypatch)
    refused = kept.check(KEPT[0])
    assert any("not in this clone" in r for r in refused), refused
    monkeypatch.delitem(kept.V1_SOURCE, sha)
    assert any("without a reviewed source commit" in r for r in kept.check(KEPT[0]))


def test_the_kept_v1_archives_are_their_commit(tmp_path):
    """Both kept archives check against kept.V1_SOURCE (needs the history: CI fetches it)."""
    for pack in KEPT:
        s = store.FileStore(kept.kept_dir(pack))
        for k in kept.manifests(s):
            assert kept.verify(pack, s, k, tmp_path / pack.name / "tree") == []


def test_a_forged_kept_build_record_is_refused(tmp_path, monkeypatch):
    """The manifest names its build record by hash: another record is refused before the archive opens."""
    if not KEPT:
        pytest.skip("no kept publication")
    pack = _forge(tmp_path, KEPT[0], lambda members: members)
    s = store.FileStore(kept.kept_dir(pack))
    m = json.loads(s.get(kept.manifests(s)[0]))
    p = kept.kept_dir(pack) / key(m["build"]["uri"])
    p.write_bytes(publish.canonical(json.loads(p.read_bytes()) | {"publisher": "0" * 64}))
    _nothing_runs(monkeypatch)
    assert any("not the hash the manifest names" in r for r in kept.check(pack))


@pytest.fixture
def copy(tmp_path):
    """A kept publication and an exact copy of it, to change one thing in the copy."""
    if not KEPT:
        pytest.skip("no kept publication")
    shutil.copytree(kept.kept_dir(KEPT[0]), tmp_path / "copy")
    return store.FileStore(kept.kept_dir(KEPT[0])), tmp_path / "copy"


def test_an_exact_copy_has_no_difference(copy):
    old, path = copy
    assert kept.differences(old, store.FileStore(path)) == []


@pytest.mark.parametrize("change", ["manifest layout", "snapshot byte", "bundle byte", "build record field", "extra file"])
def test_every_change_beyond_the_build_names_is_found(copy, change):
    old, path = copy
    new = store.FileStore(path)
    manifest = kept.manifests(new)[0]
    m = json.loads(new.get(manifest))
    target = {
        "manifest layout": manifest,
        "snapshot byte": key(m["snapshots"][0]["uri"]),
        "bundle byte": key(m["compiled"][0]["uri"]),
        "build record field": key(m["build"]["uri"]),
        "extra file": f"{manifest.split('/')[0]}/extra.json",
    }[change]
    p = path / target
    if change == "manifest layout":
        p.write_bytes((json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    elif change == "build record field":
        p.write_bytes(publish.canonical(json.loads(p.read_bytes()) | {"note": "x"}))
    elif change == "extra file":
        p.write_bytes(b"[]\n")
    else:
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n", 1))
    assert kept.differences(old, new) != []


def test_a_kept_publication_is_never_replaced(copy):
    _, path = copy
    with pytest.raises(ValueError, match="never replaced"):
        kept.make(_pack_of(path), {})
    assert kept.differences(copy[0], store.FileStore(path)) == [], "nothing was written"


def _pack_of(published):
    """A stand-in pack directory whose expected/published/ is `published`."""
    pack = published.parent / "pack"
    (pack / "expected").mkdir(parents=True, exist_ok=True)
    (pack / "expected" / "published").symlink_to(published)
    return pack


def key(uri):
    return kept.key(uri)
# Access checks with real rules: the compiler's neutral pack, read rules and every aggregate function.
ACCESS = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "alpha", x) :- {alpha}.
may_read("viewer", "beta", x) :- beta(x).
"""
DERIVED = """.decl low(b: symbol)
low(b) :- beta(b), !beta__state(b, "high").
.decl linked(b: symbol, a: symbol)
linked(b, a) :- beta__alpha(b, a).
.decl total(b: symbol, s: number)
total(b, s) :- beta(b), s = sum z : { alpha__size(_, z) }.
.decl many(b: symbol, n: number)
many(b, n) :- beta(b), n = count : { alpha(_) }.
.decl least(b: symbol, m: number)
least(b, m) :- beta(b), m = min z : { alpha__size(_, z) }.
.decl most(b: symbol, m: number)
most(b, m) :- beta(b), m = max z : { alpha__size(_, z) }.
"""
OPEN = "alpha__title(x, \"open\")"  # the viewer reads an alpha only if its title says so: alpha is not full
ALL = "alpha(x)"  # the viewer reads every alpha, by the shape of the rule: alpha is full
BETAS = "beta:\n  - {id: b1, alpha: a1, state: low}\n  - {id: b2, alpha: a2, state: high}\n"


def alphas(*rows):
    return "alpha:\n" + "".join(f"  - {{id: {i}, title: {t}, size: {s}}}\n" for i, t, s in rows)


def read_pack(tmp, grant, *rows):
    return pack_with(tmp, {"a.yaml": alphas(*rows), "b.yaml": BETAS}, ACCESS.format(alpha=grant) + DERIVED)


def viewer_files(s):
    objects = publish.role_objects(s, "minimal", "m-1", "viewer")
    keys = sorted(set(s.list("minimal/m-1/viewer/")) | set(objects.values()))
    return {k: s.get(k) for k in keys}


def test_hidden_rows_change_no_byte_of_a_role_with_real_rules(tmp_path):
    """The same pack with one more alpha the viewer may not read: the checker's count, sum and minimum
    change; the viewer, which reads alpha only in part, gets no aggregate over it and the same bytes."""
    rows = [("a1", "open", 3), ("a2", "open", 5)]
    e1, m1 = publish_pack(read_pack(tmp_path / "one", OPEN, *rows), tmp_path / "one")
    e2, m2 = publish_pack(read_pack(tmp_path / "two", OPEN, *rows, ("a3", "secret", 1)), tmp_path / "two")
    assert sorted(e1.rows["total"]) != sorted(e2.rows["total"]) and sorted(e1.rows["least"]) != sorted(e2.rows["least"])
    a, b = viewer_files(store.FileStore(tmp_path / "one" / "store")), viewer_files(store.FileStore(tmp_path / "two" / "store"))
    assert a and a == b
    seen = store.FileStore(tmp_path / "one" / "store")
    rel = lambda r: json.loads(object_bytes(seen, "viewer", f"relations/{r}.json"))
    assert [x["key"] for x in rel("low")] == [["b1"]], "negation over a relation read in full"
    assert all(rel(r) == [] for r in ("total", "many", "least", "most")), "no aggregate over alpha, read in part"
    full = {x["relation"] for x in m1["snapshots"] if x["role"] == "viewer" and x["full"]}
    assert {"beta", "beta__state", "low"} <= full and not {"alpha", "alpha__size", "total"} & full


def test_a_role_that_reads_everything_in_full_gets_what_the_checker_gets(tmp_path):
    """With an unconditional read rule on alpha too, count, sum, min and max reach the viewer."""
    e, m = publish_pack(read_pack(tmp_path, ALL, ("a1", "open", 3), ("a2", "x", 5)), tmp_path)
    s = store.FileStore(tmp_path / "store")
    mine = {x["relation"]: x for x in m["snapshots"] if x["role"] == "viewer"}
    assert all(x["full"] for x in mine.values())
    for x in m["snapshots"]:
        if x["role"] == "checker":
            assert mine[x["relation"]]["sha256"] == x["sha256"], x["relation"]
    assert object_bytes(s, "viewer", "witnesses.json") == object_bytes(s, "checker", "witnesses.json")
    assert sorted(e.rows["total"]) == [("b1", "8"), ("b2", "8")]


def test_the_command_line_names_a_role_the_read_rules_give_nothing(tmp_path, capsys, monkeypatch):
    """A role of the profile that the pack's read rules give no row (`propose` here) is published
    with nothing to read, and the publisher says so in a note; a role with rights is not named."""
    from rezono_publisher import __main__ as cli

    d = read_pack(tmp_path, ALL, ("a1", "open", 3), ("a2", "x", 5))
    roles = [a for r, mode in sorted(ROLES.items()) for a in ("--role", f"{r}={mode}")]
    # The store by path: a file URL of a Windows path is not what this test is about.
    monkeypatch.setattr(cli.store, "open_store", lambda url, endpoint=None: store.FileStore(tmp_path / "store"))
    assert cli.main([str(d), "--store", "file:///unused", *roles, "--epoch", "1",
                     "--knowledge-time", "2026-01-01T00:00:00Z", "--source", "rules=test"]) == 0
    notes = [line for line in capsys.readouterr().err.splitlines() if line.startswith("note: ")]
    assert len(notes) == 1 and notes[0].startswith("note: role propose reads no element of minimal")
    assert role_file(tmp_path, "propose", "relations/alpha.json") == []


# Calculation rules on the neutral pack: half the size of an alpha, rounded half away from zero.
HALF = """format: rezono.calc/1
pack: minimal
subject: alpha
as_of: {valid_at: "2026-06-01", known_at: "2026-06-01"}
rules:
  - id: half@1
    rule: half
    version: "1"
    output: half.value
    unit: x
    valid_from: "2026-01-01"
    valid_until: "2027-01-01"
    known_from: "2026-01-01"
    definitions:
      - name: base
        when: {boolean: true}
        value: {op: round, args: [{op: ratio, args: [{fact: alpha.size}, {integer: "1"}, {integer: "2"}]}]}
"""


def calc_pack(tmp, grant, *rows):
    d = read_pack(tmp, grant, *rows)
    (d / "calc").mkdir()
    (d / "calc" / "half.yaml").write_text(HALF, encoding="utf-8")
    return d


def role_file(tmp, role, name):
    return json.loads(object_bytes(store.FileStore(tmp / "store"), role, name))


def test_calculated_rows_are_published_with_checked_witnesses(tmp_path):
    e, m = publish_pack(calc_pack(tmp_path, ALL, ("a1", "open", 3), ("a2", "x", 5)), tmp_path)
    assert sorted(e.rows["calc__half"]) == [("a1", "2", "known", ""), ("a2", "3", "known", "")]
    assert e.rows["calc__as_of"] == [("as_of", "2026-06-01", "2026-06-01")]
    seen = role_file(tmp_path, "checker", "witnesses.json")["calc_witnesses"]
    assert [(w["conclusion"]["key"], w["version"], w["definition"]) for w in seen] == [
        ('["a1","2","known",""]', "1", "base"), ('["a2","3","known",""]', "1", "base")]
    assert [s["path"] for s in seen[1]["steps"]] == ["base/value", "base/value/0", "base/value/0/0"]
    assert {c["file"] for c in m["compiled"]} >= {"ir/calc.json"}
    # A role that reads alpha in full sees what the checker sees, witnesses included.
    assert role_file(tmp_path, "viewer", "witnesses.json") == role_file(tmp_path, "checker", "witnesses.json")


def test_a_calculation_over_a_relation_read_in_part_is_not_the_roles(tmp_path):
    """O8: a missing size would be not_applicable, so the value rests on rows the viewer may not read."""
    publish_pack(calc_pack(tmp_path, OPEN, ("a1", "open", 3), ("a2", "secret", 5)), tmp_path)
    assert role_file(tmp_path, "viewer", "relations/calc__half.json") == []
    assert role_file(tmp_path, "viewer", "witnesses.json")["calc_witnesses"] == []
    assert len(role_file(tmp_path, "checker", "relations/calc__half.json")) == 2


def test_a_filter_that_drops_visible_calculated_rows_is_red(tmp_path, monkeypatch):
    """The viewer reads alpha in full, so both calculated rows are its. A filter
    that drops them and their witnesses is red: the checker derives what the role may see itself."""
    from rezono_publisher import access

    real = access.for_role

    def lossy(*args, **kwargs):
        readable, sees, full = real(*args, **kwargs)
        readable = {rel: ([] if rel == "calc__half" else rs) for rel, rs in readable.items()}
        return readable, {**sees, "calc_witnesses": []}, full

    monkeypatch.setattr(access, "for_role", lossy)
    with pytest.raises(publish.Blocked, match=r"role (propose|viewer): .*calc_visible_missing"):
        publish_pack(calc_pack(tmp_path, ALL, ("a1", "open", 3), ("a2", "x", 5)), tmp_path)
    assert not (tmp_path / "store").exists() or store.FileStore(tmp_path / "store").list("") == []


@pytest.mark.parametrize("forgery", ["step", "version", "row", "missing", "unchecked"])
def test_a_wrong_calculation_witness_blocks(tmp_path, monkeypatch, forgery):
    real = batch.epoch

    def forged(*args, **kwargs):
        e = real(*args, **kwargs)
        w = e.calc_witnesses[0]
        if forgery == "step":  # round(3/2) half down
            w["steps"][0]["value"] = "1"
        elif forgery == "version":
            w["version"] = "2"
        elif forgery == "row":  # the published value differs from the proven one
            e.rows["calc__half"] = [("a1", "7", "known", "")] + [r for r in e.rows["calc__half"] if r[0] != "a1"]
        elif forgery == "missing":
            e = dataclasses.replace(e, calc_witnesses=e.calc_witnesses[1:])
        else:  # no program and no witnesses: the calculated rows would go out as unchecked base rows
            e = dataclasses.replace(e, calc="", calc_witnesses=[])
        return e

    monkeypatch.setattr(batch, "epoch", forged)
    d = calc_pack(tmp_path, ALL, ("a1", "open", 3), ("a2", "x", 5))
    with pytest.raises(publish.Blocked, match="rezono:proofs"):
        publish_pack(d, tmp_path)
    assert not (tmp_path / "store").exists() or store.FileStore(tmp_path / "store").list("") == []


def test_an_invalid_result_refuses_the_epoch_and_names_its_reason(tmp_path):
    """AUD-C1: a calculation result that is `invalid` never publishes, even with a right witness, and the
    refusal names it (`calc_invalid` and the result's reason), so a refused pack says why."""
    d = calc_pack(tmp_path, ALL, ("a1", "open", 0), ("a2", "x", 4))
    over_size = '{integer: "1"}, {integer: "1"}, {fact: alpha.size}'
    (d / "calc" / "half.yaml").write_text(
        HALF.replace('{fact: alpha.size}, {integer: "1"}, {integer: "2"}', over_size), encoding="utf-8")
    e, s, m, refused = run(d, tmp_path / "store")
    assert m is None and all(c["status"] != "red" for c in e.checks)
    assert "calc_invalid" in refused and "division by zero" in refused, refused


# --- The check metadata (rezono__*) comes from the definition only ----------------------------

def test_the_loaded_check_metadata_is_the_bundles_and_never_a_snapshot(tmp_path):
    from rezono_checker import metadata
    d = pack_with(tmp_path, {"a.yaml": alpha(("a1", 1))})
    e, m = publish_pack(d, tmp_path)
    loaded = {t: sorted(rs) for t, rs in e.check_metadata.items()}
    assert loaded == metadata.expected(json.loads(e.bundle)) and loaded["rezono__required"]
    assert not any(r.startswith("rezono__") for r in e.rows)
    assert not any(s["relation"].startswith("rezono__") for s in m["snapshots"])


@pytest.mark.parametrize("change", ["a row dropped", "a row added", "a row twice", "a table missing", "none loaded"])
def test_check_metadata_that_differs_from_the_bundle_blocks(tmp_path, change):
    """A required slot switched off in the engine but not in the schema must not publish (fail closed)."""
    d = pack_with(tmp_path, {"a.yaml": alpha(("a1", 1))})
    e = batch.epoch(d, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    meta = dict(e.check_metadata)
    required = meta["rezono__required"]
    meta = {"a row dropped": meta | {"rezono__required": required[1:]},
            "a row added": meta | {"rezono__required": required + [("alpha", "size")]},
            "a row twice": meta | {"rezono__required": required + required[:1]},
            "a table missing": {t: rs for t, rs in meta.items() if t != "rezono__single"},
            "none loaded": None}[change]
    s = store.FileStore(tmp_path / "store")
    with pytest.raises(publish.Blocked, match="check_metadata"):
        publish.publish(dataclasses.replace(e, check_metadata=meta), s, ROLES)
    assert s.list("") == [], "a refused epoch writes nothing"


@pytest.mark.parametrize("pack_dir", PACKS, ids=[str(p.relative_to(ROOT / "examples")) for p in PACKS])
def test_the_checker_reads_the_compilers_metadata_from_the_bundle(pack_dir):
    """Two readings of one schema agree: the compiler's rows and the checker's, from the bundle alone."""
    from rezono_checker import metadata
    from rezono_compiler import emit, pack
    model = pack.read(pack_dir)
    files = emit.compile_pack(model)
    rows = {t: [tuple(batch.text(v) for v in r.values()) for r in rs]
            for t, rs in json.loads(files["engine/parameters.json"]).items() if t.startswith("rezono__")}
    assert metadata.expected(json.loads(files["bundle/schema-bundle.json"])) == {t: sorted(r) for t, r in rows.items()}
