"""RV-M15: a pack whose newest main manifest was made from the same pack and build is not published again.

First on synthetic epochs (what counts as the same input), then through the command line on the compiler's
neutral test pack in a temp Git repository (needs the compiler and DuckDB): nothing is computed or written
for an unchanged pack, and a changed pack gets the bytes of an ordinary publication."""

import dataclasses
import json

import pytest
import yaml

from rede_publisher import pointers, publish, store
from test_publish import ROLES, epoch

BUILD = {"format": "rede.build/3", "publisher": "5" * 64}


def inputs(e, roles=ROLES) -> dict:
    return {"pack_sha256": e.pack_sha256, "engine": e.engine, "build": e.build, "roles": roles}


def test_the_newest_main_manifest_is_found_through_its_head(tmp_path):
    s = store.FileStore(tmp_path)
    assert publish.newest_main(s, "toy") is None
    for n in (1, 3, 2):  # the head key sorts the newest first, whatever the order of writing
        publish.publish(epoch(epoch=n), s, ROLES)
    assert publish.newest_main(s, "toy") == json.loads(s.get("toy/manifests/m-3.json"))
    # A proposal on it has a pointer, not a head: it is never the newest main.
    publish.publish(epoch(epoch=4, proposal="7", base_manifest="m-3"), s, ROLES)
    assert publish.newest_main(s, "toy")["id"] == "m-3"


@pytest.mark.parametrize("body", [b"{}", b"not json", b'{"manifest": "m-9"}', None])
def test_a_head_that_is_not_the_head_of_its_manifest_is_an_error(tmp_path, body):
    s = store.FileStore(tmp_path)
    publish.publish(epoch(), s, ROLES)
    if body is None:  # the head of m-1, under the key of a newer epoch
        body = s.get(pointers.head_key("toy", 1))
    s.put_new(pointers.head_key("toy", 5), body)
    with pytest.raises(ValueError, match="is not a head"):
        publish.newest_main(s, "toy")


def test_a_manifest_made_from_the_same_pack_engine_build_and_roles_is_unchanged(tmp_path):
    e = epoch(build=BUILD)
    s = store.FileStore(tmp_path)
    m = publish.publish(e, s, ROLES)
    assert publish.unchanged(m, **inputs(e))
    # The epoch, the knowledge time and the commit are no inputs: a later commit that leaves the pack and the
    # build alone would publish the same rows, proofs and views under another number.
    later = dataclasses.replace(e, epoch=7, knowledge_time="2026-02-02T00:00:00Z", sources=[("rules", "def")])
    assert publish.unchanged(m, **inputs(later))
    # The record compared is the one published: what the manifest names is these bytes.
    record = publish.build_bytes(e.build, ROLES)
    assert m["build"]["sha256"] == publish.sha256(record)
    assert s.get(m["build"]["uri"].removeprefix("s3://rede/")) == record


@pytest.mark.parametrize("change", [
    {"pack_sha256": "9" * 64},
    {"engine": {"name": "test", "version": "1", "sha256": "3" * 64}},
    {"build": BUILD | {"publisher": "6" * 64}},
    {"build": BUILD | {"views": {"format": "rede.view-build/1"}}},
    {"roles": ROLES | {"auditor": "may_read"}},
    {"roles": {"checker": "complete", "guest": "complete"}},
])
def test_any_other_pack_engine_build_or_role_is_a_change(tmp_path, change):
    e = epoch(build=BUILD)
    m = publish.publish(e, store.FileStore(tmp_path), ROLES)
    assert not publish.unchanged(m, **inputs(e) | change)


def test_what_cannot_be_compared_counts_as_a_change(tmp_path):
    e = epoch()  # no build record: an older caller
    m = publish.publish(e, store.FileStore(tmp_path), ROLES)
    assert "build" not in m
    assert not publish.unchanged(m, **inputs(e))
    assert not publish.unchanged(m, **inputs(e) | {"build": BUILD})
    assert not publish.unchanged(None, **inputs(epoch(build=BUILD)))
    assert not publish.unchanged({}, **inputs(epoch(build=BUILD)))


# Through the command line, on a real pack.

pytest.importorskip("duckdb")
pytest.importorskip("rede_compiler")

from rede_publisher import __main__ as cli, batch, sweep  # noqa: E402
from test_sweep import FACTS, IDS, PACK, commit, publish_main, repo, sh, tree  # noqa: E402, F401

PROFILE = {"checker": "complete", "viewer": "may_read"}


def run(repo, st, monkeypatch, *extra) -> int:
    """`python -m rede_publisher` for the pack at HEAD, as publish.sh calls it (without the views: no Node here)."""
    monkeypatch.setattr(cli.store, "open_store", lambda *a: st)
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    n, time = sweep.base_of(repo, base)
    return cli.main([str(repo / PACK), "--store", "file://unused", *(f"--role={r}={m}" for r, m in PROFILE.items()),
                     "--epoch", str(n), "--knowledge-time", time, "--source", f"rules={base}", *extra])


def test_an_unchanged_pack_is_not_published_again_and_nothing_is_written(repo, tmp_path, monkeypatch, capsys):
    st = store.FileStore(tmp_path / "store")
    assert run(repo, st, monkeypatch, "--skip-unchanged") == 0  # nothing is published yet: m-2
    assert capsys.readouterr().out == "m-2\n"
    before = tree(tmp_path / "store")
    commit(repo, "a commit that leaves the pack alone")
    with monkeypatch.context() as m:
        m.setattr(batch, "epoch", lambda *a, **k: pytest.fail("an epoch was computed for an unchanged pack"))
        assert run(repo, st, m, "--skip-unchanged") == 0
    said = capsys.readouterr()
    assert said.out == "m-2\n" and "unchanged" in said.err
    assert tree(tmp_path / "store") == before
    # Without the flag every epoch is published, as before.
    assert run(repo, st, monkeypatch) == 0
    assert capsys.readouterr().out == "m-3\n"


def test_a_changed_pack_is_published_with_the_bytes_of_an_ordinary_publication(repo, tmp_path, monkeypatch):
    skipping, ordinary = store.FileStore(tmp_path / "a"), store.FileStore(tmp_path / "b")
    assert run(repo, skipping, monkeypatch, "--skip-unchanged") == 0
    assert run(repo, ordinary, monkeypatch) == 0
    (repo / PACK / "facts" / "a.yaml").write_text(FACTS.replace("title: u", "title: w"))
    commit(repo, "a fact")
    assert run(repo, skipping, monkeypatch, "--skip-unchanged") == 0
    assert run(repo, ordinary, monkeypatch) == 0
    assert skipping.get("minimal/manifests/m-3.json") is not None
    assert publish.newest_main(skipping, "minimal")["id"] == "m-3"
    assert tree(tmp_path / "a") == tree(tmp_path / "b")


def test_another_build_or_another_profile_is_published(repo, tmp_path, monkeypatch, capsys):
    st = store.FileStore(tmp_path / "store")
    assert run(repo, st, monkeypatch, "--skip-unchanged") == 0
    commit(repo, "elsewhere")
    other_profile = ("--skip-unchanged", "--role", "viewer=complete")
    assert run(repo, st, monkeypatch, *other_profile) == 0  # m-3: the profile gives another role
    commit(repo, "elsewhere again")
    record = batch.build_record()
    with monkeypatch.context() as m:
        m.setattr(batch, "build_record", lambda: record | {"publisher": "0" * 64})
        assert run(repo, st, m, *other_profile) == 0  # m-4: the same profile, another publisher
    commit(repo, "and again")
    assert run(repo, st, monkeypatch, *other_profile) == 0  # m-5: the publisher of before; m-4 is the newest
    commit(repo, "and once more")
    assert run(repo, st, monkeypatch, *other_profile) == 0  # nothing: m-5 is of this pack, build and profile
    assert capsys.readouterr().out == "m-2\nm-3\nm-4\nm-5\nm-5\n"


def test_a_pack_the_compiler_would_refuse_is_never_skipped(repo, tmp_path, monkeypatch):
    st = store.FileStore(tmp_path / "store")
    assert run(repo, st, monkeypatch) == 0
    assert cli.published(str(repo / PACK), st, PROFILE, False)["id"] == "m-2"
    from rede_compiler import modules

    def refuse(pack_dir):
        raise ValueError("import std-x is not the pinned one")

    monkeypatch.setattr(modules, "closure", refuse)
    assert cli.published(str(repo / PACK), st, PROFILE, False) is None


def test_the_sweep_varies_the_newest_main_manifest_when_head_published_nothing(repo, tmp_path, monkeypatch):
    st = store.FileStore(tmp_path / "store")
    profile = tmp_path / "profile.yaml"
    profile.write_text(yaml.safe_dump({"storage": {"url": "file://unused"}, "access": {"roles": PROFILE}}))
    monkeypatch.setattr(sweep.store, "open_store", lambda *a: st)
    args = [PACK, "--profile", str(profile), "--repo", str(repo), "--newest"]
    assert sweep.main(args) == 1  # no main manifest: "base not published", as for a commit without one
    base = publish_main(repo, st)
    commit(repo, "a commit that leaves the pack alone")  # HEAD is epoch 3; the pack is published as m-2
    assert sweep.newest_commit(repo, PACK, st) == base
    assert sweep.main(args) == 0
    assert st.get(f"minimal/manifests/{IDS[0]}.json") is not None  # v-…-3: against m-2, where the gate looks
    whole = tree(tmp_path / "store")
    assert sweep.main(args) == 0  # and again: every variant is kept
    assert tree(tmp_path / "store") == whole
