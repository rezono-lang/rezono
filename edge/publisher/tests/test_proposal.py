"""The manifest of a proposal: the delta on the pack at its base commit, published next to the main manifest
it refers to. On the compiler's neutral test pack in a temp Git repository (needs the compiler and DuckDB)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, proof, proposal, publish, store  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PACK = "packs/p"
ROLES = {"checker": "complete", "viewer": "may_read"}
FACTS = "alpha:\n  - {id: a1, title: t, size: 1}\n  - {id: a2, title: u, size: 1}\n"
SET_A1 = json.dumps({"format": "rezono.delta/1", "changes": [
    {"op": "set", "file": "facts/a.yaml", "kind": "alpha", "key": "a1", "slot": "size", "value": 2}]})


def object_bytes(s, role, name, mid="m-1"):
    return s.get(publish.role_objects(s, "minimal", mid, role)[name])


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A repository with one pack, two commits; main is published at the base commit (epoch 2)."""
    r = tmp_path / "repo"
    shutil.copytree(ROOT / "compiler" / "tests" / "fixtures" / "minimal", r / PACK)
    (r / PACK / "facts").mkdir()
    (r / PACK / "facts" / "a.yaml").write_text(FACTS)
    sh("git", "init", "-q", "-b", "main", cwd=r)
    for message in ("seed", "base"):
        (r / "log.txt").write_text(message)
        sh("git", "add", ".", cwd=r)
        sh("git", "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", message, cwd=r)
    return r


def publish_main(repo, st):
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    n, time = proposal.base_of(repo, base)
    e = batch.epoch(repo / PACK, epoch=n, knowledge_time=time, sources=[("rules", base)])
    return base, publish.publish(e, st, ROLES)


def size(st, mid, key):
    rows = json.loads(object_bytes(st, "checker", "relations/alpha__size.json", mid))
    return {r["key"][0]: r["key"][1] for r in rows}[key]


def test_a_proposal_is_published_next_to_its_base(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, m = publish_main(repo, st)
    assert m["id"] == "m-2"
    mid = proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    assert mid == "p-7-3"
    got = json.loads(st.get("minimal/manifests/p-7-3.json"))
    assert (got["proposal"], got["base_manifest"], got["epoch"]) == ("7", "m-2", 3)
    assert got["sources"] == [{"source_id": "rules", "position": base}]
    assert size(st, "m-2", "a1") == "1" and size(st, "p-7-3", "a1") == "2"
    assert {s["role"] for s in got["snapshots"]} == set(ROLES)
    # The repository is as it was: the delta went to a private work dir, never to the checkout.
    assert sh("git", "status", "--porcelain", cwd=repo) == ""
    assert (repo / PACK / "facts" / "a.yaml").read_text() == FACTS
    assert sh("git", "worktree", "list", "--porcelain", cwd=repo).count("worktree ") == 1


def test_a_repeat_keeps_the_manifest(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    before = {k: st.get(k) for k in st.list("")}
    assert proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES) == "p-7-3"
    assert {k: st.get(k) for k in st.list("")} == before


def test_a_repeat_writes_the_pointer_a_stopped_run_left_out(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    [ref] = [k for k in st.list("") if "/bases/" in k]
    before = st.get(ref)
    st._path(ref).unlink()  # the run stopped between the manifest and its pointer
    assert proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES) == "p-7-3"
    assert st.get(ref) == before


def test_an_unpublished_base_is_refused(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base = sh("git", "rev-parse", "HEAD~1", cwd=repo)  # main was never published at this commit
    with pytest.raises(ValueError, match="base not published"):
        proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    assert st.list("") == []


def test_a_red_proposal_writes_nothing(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    too_big = json.dumps({"format": "rezono.delta/1", "changes": [  # size has maximum 9: a violation, red
        {"op": "set", "file": "facts/a.yaml", "kind": "alpha", "key": "a1", "slot": "size", "value": 12}]})
    before = st.list("")
    with pytest.raises(publish.Blocked):
        proposal.publish_proposal(repo, PACK, "8", base, too_big, st, ROLES)
    assert st.list("") == before


@pytest.mark.parametrize("pack, pr, commit", [("../p", "7", None), (PACK, "07", None), (PACK, "7", "abc")])
def test_bad_input_is_refused(repo, tmp_path, pack, pr, commit):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        proposal.publish_proposal(repo, pack, pr, commit or base, SET_A1, st, ROLES)


def test_a_corrupted_witness_writes_nothing(repo, tmp_path, monkeypatch):
    """R7: the independent checker runs before any write, also on this path."""
    import dataclasses

    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    real = batch.epoch

    def corrupted(*args, **kwargs):
        e = real(*args, **kwargs)
        broken = {"conclusion": {"relation": "nowhere", "key": '["x"]'}, "rule_id": "nothing", "premises": []}
        return dataclasses.replace(e, witnesses=[*e.witnesses, broken])

    monkeypatch.setattr(batch, "epoch", corrupted)
    before = {k: st.get(k) for k in st.list("")}
    with pytest.raises(publish.Blocked, match="rezono:proofs"):
        proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    assert {k: st.get(k) for k in st.list("")} == before


def test_a_base_of_another_commit_with_as_many_ancestors_is_refused(repo, tmp_path):
    """Two sibling commits have the same count; m-N belongs to one of them only."""
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    sh("git", "checkout", "-q", "-b", "other", "HEAD~1", cwd=repo)
    (repo / "log.txt").write_text("sibling")
    sh("git", "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-qam", "sibling", cwd=repo)
    sibling = sh("git", "rev-parse", "HEAD", cwd=repo)
    assert proposal.base_of(repo, sibling)[0] == proposal.base_of(repo, base)[0]
    with pytest.raises(ValueError, match="not of commit"):
        proposal.publish_proposal(repo, PACK, "7", sibling, SET_A1, st, ROLES)


def test_a_published_proposal_of_another_base_is_not_taken_for_this_one(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    key = "minimal/manifests/p-7-3.json"
    forged = {**json.loads(st.get(key)), "sources": [{"source_id": "rules", "position": "0" * 40}]}
    (tmp_path / "store" / key).write_text(json.dumps(forged))
    with pytest.raises(ValueError, match="another base"):
        proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)


def test_two_fresh_runs_give_the_same_bytes(repo, tmp_path):
    a, b = store.FileStore(tmp_path / "a"), store.FileStore(tmp_path / "b")
    for st in (a, b):
        base, _ = publish_main(repo, st)
        proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    assert a.list("") == b.list("") and all(a.get(k) == b.get(k) for k in a.list(""))


def test_an_oversized_delta_is_refused_before_it_is_read(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    with pytest.raises(ValueError, match="larger than"):
        proposal.publish_proposal(repo, PACK, "7", base, " " * (proposal.MAX_DELTA + 1), st, ROLES)


def test_a_symbolic_link_in_the_pack_is_refused(repo, tmp_path):
    """The writer writes only in its work dir, never through a link out of it."""
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    (repo / PACK / "facts").rename(repo / "elsewhere")
    (repo / PACK / "facts").symlink_to(repo / "elsewhere")
    sh("git", "add", "-A", cwd=repo)
    sh("git", "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-qm", "link", cwd=repo)
    linked = sh("git", "rev-parse", "HEAD", cwd=repo)
    n, time = proposal.base_of(repo, linked)
    e = batch.epoch(repo / PACK, epoch=n, knowledge_time=time, sources=[("rules", linked)])
    publish.publish(e, st, ROLES)
    from rezono_compiler import writer

    with pytest.raises((ValueError, writer.WriteError)):
        proposal.publish_proposal(repo, PACK, "7", linked, SET_A1, st, ROLES)


@pytest.mark.parametrize("value", ["!!python/object/apply:os.system [x]", "*alias", "&anchor v", "{a: 1}"])
def test_yaml_syntax_in_a_value_stays_text(repo, tmp_path, value):
    """A tag, alias, anchor or flow mapping in a value is written as text, never interpreted."""
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    delta = json.dumps({"format": "rezono.delta/1", "changes": [
        {"op": "set", "file": "facts/a.yaml", "kind": "alpha", "key": "a1", "slot": "title", "value": value}]})
    mid = proposal.publish_proposal(repo, PACK, "7", base, delta, st, ROLES)
    rows = json.loads(object_bytes(st, "checker", "relations/alpha__title.json", mid))
    assert {r["key"][0]: r["key"][1] for r in rows}["a1"] == value


def test_a_proposal_has_its_difference_per_role_the_gate_serves(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    # The complete role is server side: no difference. The viewer reads no element of this pack, so its
    # difference is empty: it shows nothing the role may not read.
    assert st.get("minimal/p-7-3/checker/explain/index.json") is None
    index = json.loads(st.get("minimal/p-7-3/viewer/explain/index.json"))
    assert (index["format"], index["manifest"], index["base_manifest"], index["role"]) == (
        "rezono.explain-index/1", "p-7-3", "m-2", "viewer")
    assert index["difference"]["counts"] == {} and index["difference"]["trees"] == {}
    assert set(index["proof"]["trees"]) == set(proof.TREES)


def test_a_difference_shows_the_changed_cell(repo, tmp_path):
    from rezono_publisher import difference

    st = store.FileStore(tmp_path / "store")
    base, _ = publish_main(repo, st)
    proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, {"checker": "complete", "viewer": "complete"})
    # Every role complete: none is served, so no difference is made. Made for a served role, the checker's
    # snapshots compared give exactly the one changed cell.
    assert difference.plan(st, "minimal", "p-7-3") == []
    m = json.loads(st.get("minimal/manifests/p-7-3.json"))
    b = json.loads(st.get("minimal/manifests/m-2.json"))
    for man in (m, b):
        for s in man["snapshots"]:
            s["complete"] = False
    files = dict(difference.plan_role(st, "minimal", "p-7-3", m, b, "checker"))
    index = json.loads(files["minimal/p-7-3/checker/explain/index.json"])
    assert index["difference"]["counts"] == {"alpha__size": {"added": 0, "removed": 0, "changed": 1}}
    leaf = json.loads(files["minimal/p-7-3/checker/explain/difference/alpha__size/0/0.json"])
    assert leaf["rows"] == [{"key": ["a1", "2"], "change": "changed", "was": ["a1", "1"]}]


# RV-M17: a proposal names who stated what it writes.
GIT = {"kind": "git", "name": "example/model", "revision": "a" * 40, "position": "corpus/snapshot.json"}
WHO, AT = "user-123 <0123456789abcdef@users.noreply.invalid>", "2026-11-10T21:03:11Z"
STATED = {"kind": "person", "name": "user-123", "position": AT}


def test_a_proposal_states_its_proposer_as_the_source_of_what_it_writes(repo, tmp_path):
    from rezono_compiler import writer

    (repo / PACK / "facts" / "a.sources.yaml").write_text("default: " + json.dumps(GIT) + "\n")  # as an ingest leaves it
    sh("git", "add", ".", cwd=repo)
    sh("git", "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", "companion", cwd=repo)
    st = store.FileStore(tmp_path / "store")
    base, m = publish_main(repo, st)
    assert m["id"] == "m-3"
    with pytest.raises(writer.WriteError, match="need their real origin"):  # no proposer: refused, nothing published
        proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES)
    assert st.get("minimal/manifests/p-7-4.json") is None
    assert proposal.stated_by(WHO, AT) == {"sources": [STATED]}  # the same origin as rezono_githost.propose builds
    mid = proposal.publish_proposal(repo, PACK, "7", base, SET_A1, st, ROLES, proposal.stated_by(WHO, AT))
    assert mid == "p-7-4" and size(st, mid, "a1") == "2"
    sources = {(e["row"]["relation"], e["row"]["key"]): e["sources"]
               for e in json.loads(object_bytes(st, "checker", "sources.json", mid))}
    assert sources[("alpha__size", '["a1","2"]')] == [STATED]  # who stated it and when, and nothing else
    assert sources[("alpha__title", '["a1","t"]')] == sources[("alpha__size", '["a2","1"]')] == [GIT]


@pytest.mark.parametrize("who,at,message", [
    ("", AT, "needs its verified proposer"), (WHO, "", "needs its verified proposer"),
    ("user-123", AT, "needs its verified proposer"),
    ("Een Gebruiker <gebruiker@example.invalid>", AT, "a plain identifier"),
    (WHO, "2026-11-10 21:03", "a real UTC instant"),
])
def test_the_command_takes_no_proposal_without_its_verified_proposer(repo, tmp_path, monkeypatch, capsys, who, at, message):
    """Before the profile and the store: nothing is read or written."""
    monkeypatch.setenv("DELTA", SET_A1)
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    args = [PACK, "--profile", str(tmp_path / "no-profile.yaml"), "--store", (tmp_path / "store").as_uri(), "--repo", str(repo),
            "--proposal", "7", "--base-commit", base, "--delta-env", "DELTA"]
    assert proposal.main([*args, *(["--co-author", who] if who else []), *(["--proposed-at", at] if at else [])]) == 1
    assert message in capsys.readouterr().err
    assert not (tmp_path / "store").exists()
