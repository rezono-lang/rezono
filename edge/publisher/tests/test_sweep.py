"""Sweep v1: one epoch per grid value after main, a manifest when green, a diagnosis when red, never a block of
main. On the compiler's neutral test pack in a temp Git repository (needs the compiler and DuckDB)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, publish, store, sweep  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PACK = "packs/p"
ROLES = {"checker": "complete", "viewer": "may_read"}
FACTS = "alpha:\n  - {id: a1, title: t, size: 1}\n  - {id: a2, title: u, size: 1}\n"
# Values 0, 3, 6, 9; a size of 6 or more needs the title "big", so 6 and 9 are red.
EXPLORE = {"value": {"step": 3}}
RULE = {"preconditions": {"slot_conditions": {"size": {"minimum_value": 6}}},
        "postconditions": {"slot_conditions": {"title": {"equals_string": "big"}}}}
SWEEPS = {"sweeps": [{"name": "size_scale", "kind": "alpha", "key": "a1", "slot": "size"}]}
IDS = [f"v-size_scale-0{i}-3" for i in range(4)]


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(r: Path, message: str) -> None:
    (r / "log.txt").write_text(message)
    sh("git", "add", ".", cwd=r)
    sh("git", "-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", message, cwd=r)


@pytest.fixture
def repo(tmp_path):
    """A repository with one pack and its sweep, two commits; main is epoch 2."""
    r = tmp_path / "repo"
    shutil.copytree(ROOT / "compiler" / "tests" / "fixtures" / "minimal", r / PACK)
    (r / PACK / "facts").mkdir()
    (r / PACK / "facts" / "a.yaml").write_text(FACTS)
    path = r / PACK / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Alpha"]["attributes"]["size"]["annotations"] = {"explore": EXPLORE}
    schema["classes"]["Alpha"]["rules"] = [RULE]
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    (r / PACK / "sweeps.yaml").write_text(yaml.safe_dump(SWEEPS, sort_keys=False))
    sh("git", "init", "-q", "-b", "main", cwd=r)
    commit(r, "seed")
    commit(r, "base")
    return r


def publish_main(repo, st):
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    n, time = sweep.base_of(repo, base)
    e = batch.epoch(repo / PACK, epoch=n, knowledge_time=time, sources=[("rules", base)])
    publish.publish(e, st, ROLES)
    return base


def tree(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def test_each_grid_value_is_a_manifest_or_a_diagnosis_against_main(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base = publish_main(repo, st)
    main_before = st.get("minimal/manifests/m-2.json")
    # The grid is archived with main, so the gate knows every value, also one not computed yet.
    archived = {f["file"]: f for f in json.loads(main_before)["compiled"]}
    grid = json.loads(st.get(archived["ir/sweeps.json"]["uri"].removeprefix("s3://rezono/")))
    assert grid["sweeps"][0]["count"] == 4
    done = sweep.run(repo, PACK, base, st, ROLES)
    assert done == [(IDS[0], "manifest"), (IDS[1], "manifest"), (IDS[2], "diagnosis"), (IDS[3], "diagnosis")]
    for i, vid in enumerate(IDS[:2]):
        m = json.loads(st.get(f"minimal/manifests/{vid}.json"))
        assert (m["id"], m["epoch"], m["base_manifest"]) == (vid, 3, "m-2")
        # The viewer reads no element of this pack, so it may not read the cell and gets no variant.
        assert m["variant"] == {"sweep": "size_scale", "index": i, "value": str(3 * i),
                                "readers": ["checker"], "status_readers": ["checker"]}
        assert {s["role"] for s in m["snapshots"]} == {"checker"}
        rows = json.loads(st.get(publish.role_objects(st, "minimal", vid, "checker")["relations/alpha__size.json"]))
        assert {r["key"][0]: r["key"][1] for r in rows} == {"a1": str(3 * i), "a2": "1"}
    for i, vid in enumerate(IDS[2:], 2):
        assert st.get(f"minimal/manifests/{vid}.json") is None
        d = json.loads(st.get(f"minimal/diagnoses/{vid}.json"))
        assert (d["id"], d["epoch"], d["last_good_manifest"]) == (vid, 3, "m-2")
        assert d["variant"]["index"] == i and d["variant"]["value"] == str(3 * i)
        assert any(c["status"] == "red" for c in d["checks"])
    # Main is as it was, and so is the repository: the deltas went to a private work dir.
    assert st.get("minimal/manifests/m-2.json") == main_before
    assert sh("git", "status", "--porcelain", cwd=repo) == ""
    assert (repo / PACK / "facts" / "a.yaml").read_text() == FACTS
    assert sh("git", "worktree", "list", "--porcelain", cwd=repo).count("worktree ") == 1


def test_a_variant_writes_only_what_the_swept_cell_changes(repo, tmp_path):
    """The promote job timed out on 526 writes per variant of the lab, 30 of them changed (07-11): a variant names
    m-N's object wherever it has the same bytes, so only the changed snapshots and witness sets are new."""
    st = store.FileStore(tmp_path / "store")
    base = publish_main(repo, st)
    main = json.loads(st.get("minimal/manifests/m-2.json"))
    of_main = {(s["role"], s["relation"]): s for s in main["snapshots"]}
    before = set(st.list(""))
    sweep.run(repo, PACK, base, st, ROLES)
    new = set(st.list("")) - before
    for vid in IDS[:2]:
        m = json.loads(st.get(f"minimal/manifests/{vid}.json"))
        own = {x["uri"].removeprefix(st.uri("")) for x in m["snapshots"] + m["witnesses"]} & new
        for s in m["snapshots"]:
            same = of_main[(s["role"], s["relation"])]["sha256"] == s["sha256"]
            old = of_main[(s["role"], s["relation"])]
            key = s["uri"].removeprefix(st.uri(""))
            assert (s["uri"] == old["uri"]) is same
            assert (key not in new) is same
            assert publish.sha256(st.get(s["uri"].removeprefix("s3://rezono/"))) == s["sha256"]
        assert own and all(x["role"] == "checker" for x in m["snapshots"] + m["witnesses"]
                           if x["uri"].removeprefix(st.uri("")) in own)
        assert publish.role_objects(st, "minimal", vid, "checker")["relations/alpha__size.json"] in own
        assert len(own) < len(m["snapshots"])
        assert {c["uri"] for c in m["compiled"]} <= {c["uri"] for c in main["compiled"]}


def test_a_stopped_run_is_completed_by_the_next_with_the_same_bytes(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base = publish_main(repo, st)
    sweep.run(repo, PACK, base, st, ROLES)
    whole = tree(tmp_path / "store")
    # As if the job stopped before the last two values: they are not there, so "not computed". A variant's own
    # objects are keyed by their bytes (RV-Z01): those only its manifest names go, found through their uris.
    root = tmp_path / "store" / "minimal"
    (root / "diagnoses" / f"{IDS[3]}.json").unlink()
    named = {p.stem: publish.named(json.loads(p.read_bytes())) for p in (root / "manifests").glob("*.json")}
    mine = named.pop(IDS[1]) - set().union(*named.values())
    assert mine
    for uri in mine:
        (tmp_path / "store" / uri.removeprefix(st.uri(""))).unlink()
    shutil.rmtree(root / IDS[1], ignore_errors=True)  # its views, when it has any
    (root / "manifests" / f"{IDS[1]}.json").unlink()
    done = sweep.run(repo, PACK, base, st, ROLES)
    assert done == [(IDS[0], "manifest kept"), (IDS[1], "manifest"), (IDS[2], "diagnosis kept"), (IDS[3], "diagnosis")]
    assert tree(tmp_path / "store") == whole


def readable(repo) -> None:
    """The viewer reads the swept kind (unlike the original fixture), so each variant has its differences."""
    rules = repo / PACK / "rules"
    rules.mkdir(exist_ok=True)
    (rules / "access.dl").write_text(
        '.decl may_read(role: symbol, kind: symbol, element: symbol)\n'
        'may_read("viewer", "alpha", x) :- alpha(x).\n'
        'may_read("viewer", "beta", x) :- beta(x).\n.output may_read\n')
    commit(repo, "readable sweep")


def test_a_kept_variant_with_its_differences_costs_a_lookup(repo, tmp_path):
    """RV-M15: a sweep with nothing to compute made every difference again, 478 writes per variant of the lab,
    each answered "there already". The role's index is written after its pieces, so finding it is enough."""
    readable(repo)

    class Counting(store.FileStore):
        reads, writes = [], []

        def get(self, key):
            self.reads.append(key)
            return super().get(key)

        def put_new(self, key, data):
            self.writes.append(key)
            super().put_new(key, data)

    st = Counting(tmp_path / "store")
    base = publish_main(repo, st)
    sweep.run(repo, PACK, base, st, ROLES)
    whole = tree(tmp_path / "store")
    indexes = sorted(k for k in whole if k.endswith("/explain/index.json"))
    assert indexes and any("/explain/difference/" in k for k in whole)
    st.reads.clear(), st.writes.clear()
    assert all(result.endswith(" kept") for _, result in sweep.run(repo, PACK, base, st, ROLES))
    assert st.writes == [] and tree(tmp_path / "store") == whole
    assert {k for k in st.reads if "/explain/" in k} == set(indexes)  # no piece is read, none is made
    # A run that stopped before a role's index: its differences are made again, the same bytes.
    (tmp_path / "store" / indexes[0]).unlink()
    sweep.run(repo, PACK, base, st, ROLES)
    assert indexes[0] in st.writes and tree(tmp_path / "store") == whole
    variant = indexes[0].split("/")[1]
    assert all(k.startswith(f"minimal/{variant}/") for k in st.writes), "only the variant that was not whole"


def test_difference_reads_are_reused_without_changing_any_published_byte(repo, tmp_path, monkeypatch):
    """A readable sweep (unlike the original fixture) exercises difference publishing after #224."""
    from collections import Counter

    readable(repo)
    original_cache = sweep.SweepStore

    class Counting(store.FileStore):
        def __init__(self, path):
            super().__init__(path)
            self.reads = Counter()

        def get(self, key):
            self.reads[key] += 1
            return super().get(key)

    class Uncached(original_cache):
        def _cacheable(self, key):
            return False

    outputs, reads = [], []
    for name, adapter in (("cached", original_cache), ("uncached", Uncached)):
        monkeypatch.setattr(sweep, "SweepStore", adapter)
        st = Counting(tmp_path / name)
        base = publish_main(repo, st)
        st.reads.clear()
        sweep.run(repo, PACK, base, st, ROLES)
        outputs.append(tree(tmp_path / name))
        reads.append(st.reads.copy())
        # A new process-local cache must also finish an already published sweep without changing bytes.
        resumed = sweep.run(repo, PACK, base, st, ROLES)
        assert all(result.endswith(" kept") for _, result in resumed)
        assert tree(tmp_path / name) == outputs[-1]
    assert outputs[0] == outputs[1]
    assert any("/explain/index.json" in key for key in outputs[0])
    base_reads = {k: n for k, n in reads[0].items() if k.startswith("minimal/m-3/")}
    assert base_reads and all(n == 1 for n in base_reads.values())
    assert sum(reads[0].values()) < sum(reads[1].values())


REACH = ('.decl sized(x: symbol, s: number)\nsized(x, s) :- alpha__size(x, s).\n.output sized\n'
         '.decl titled(x: symbol, t: symbol)\ntitled(x, t) :- alpha__title(x, t).\n.output titled\n')


def rows_of(files: dict, root: dict) -> list:
    """The rows of one proof tree as a reader gets them: from the root an index names, every piece by the
    sha256 that names it, a page's children under the root's own prefix."""
    key = root["uri"].removeprefix("s3://rezono/")
    home = key[:key.index("/proof/")]

    def walk(path, digest):
        data = files[f"{home}/{path}"]
        assert publish.sha256(data) == digest
        piece = json.loads(data)
        return piece["rows"] if piece["level"] == 0 else [r for c in piece["children"] for r in walk(c["file"], c["sha256"])]

    return walk(key.removeprefix(home + "/"), root["sha256"])


def test_a_variant_names_the_proof_trees_of_its_base_and_writes_only_the_others(repo, tmp_path):
    """RV-M24: a variant of the lab wrote 801 proof pieces, 521 of them the bytes of its base's views. Where the
    base's view index names a tree with the same root hash, the explain index names that root and the variant
    writes no copy; a tree the swept cell reaches is the variant's own. Every tree reads the same rows either
    way, and without a view index of the base (the first store) nothing changes."""
    from rezono_publisher import views

    readable(repo)
    (repo / PACK / "rules" / "reach.dl").write_text(REACH)
    commit(repo, "a rule the swept cell reaches and one it does not")
    copies, named = store.FileStore(tmp_path / "copies"), store.FileStore(tmp_path / "named")
    for st in (copies, named):
        base = publish_main(repo, st)
    mid = f"m-{sweep.base_of(repo, base)[0]}"
    # The `proof` part of the viewer's view index of the base with its pieces, as views.plan makes them (the
    # sheets of a whole index need Node, and nothing here reads them).
    m = json.loads(named.get(f"minimal/manifests/{mid}.json"))
    snapshots = views._snapshots(named, [s for s in m["snapshots"] if s["role"] == "viewer"])
    made, part = views._proof(named, "minimal", mid, m, "viewer", snapshots)
    store.put_all(named, made + [(views.index_key("minimal", mid, "viewer"), views.dumps({"proof": part}))])
    of_base = tree(tmp_path / "named")
    assert sweep.run(repo, PACK, base, copies, ROLES) == sweep.run(repo, PACK, base, named, ROLES)
    a, b = tree(tmp_path / "copies"), tree(tmp_path / "named")
    assert of_base.items() <= b.items() and set(b) - set(a) == set(of_base) - set(a)  # the base is as it was
    left_out = set(a) - set(b)
    indexes = sorted(k for k in a if k.endswith("/explain/index.json"))
    assert len(indexes) == 2 and {k for k in set(a) & set(b) if a[k] != b[k]} == set(indexes)
    where = {}
    for k in indexes:
        ia, ib = json.loads(a[k]), json.loads(b[k])
        assert ib | {"proof": ib["proof"] | {"trees": ia["proof"]["trees"]}} == ia  # only the roots differ
        for t, by in ia["proof"]["trees"].items():
            for rel, ra in by.items():
                rb = ib["proof"]["trees"][t][rel]
                assert rows_of(a, ra) == rows_of(b, rb) and rb | {"uri": ra["uri"]} == ra
                own = {p for p in a if p.startswith(f"{k.removesuffix('/index.json')}/proof/{t}/{rel}/")}
                if rb == ra:
                    assert own and own <= set(b)
                else:  # the base's root, and no piece of the copy
                    assert rb == part["trees"][t][rel] and own and own <= left_out
                    left_out -= own
                where.setdefault((t, rel), set()).add(rb != ra)
    assert left_out == set()  # nothing else is missing
    assert where[("witness", "titled")] == {True} and where[("witness", "may_read")] == {True}
    assert where[("witness", "sized")] == {False} and where[("forward", "alpha__size")] == {False}
    # A repeat finds every variant whole and writes nothing.
    assert all(result.endswith(" kept") for _, result in sweep.run(repo, PACK, base, named, ROLES))
    assert tree(tmp_path / "named") == b


def test_progress_and_timings_are_reported_also_when_a_variant_fails(repo, tmp_path, monkeypatch, capfd):
    st = store.FileStore(tmp_path / "store")
    base = publish_main(repo, st)

    def interrupted(*args):
        raise store.Conflict("stopped")

    monkeypatch.setattr(sweep, "kept", interrupted)
    with pytest.raises(store.Conflict):
        sweep.run(repo, PACK, base, st, ROLES)
    log = capfd.readouterr().err
    assert f"sweep {PACK}/{IDS[0]} start" in log
    assert f"time {PACK}/{IDS[0]} total " in log
    assert f"sweep {PACK}/{IDS[0]} error get=" in log
    assert "hit=" in log and "put=" in log and "get_bytes=" in log and "put_bytes=" in log
    assert f"sweep {PACK}/{IDS[0]} lookup start" in log


def test_two_fresh_runs_give_the_same_bytes(repo, tmp_path):
    out = []
    for name in ("a", "b"):
        st = store.FileStore(tmp_path / name)
        sweep.run(repo, PACK, publish_main(repo, st), st, ROLES)
        out.append(tree(tmp_path / name))
    assert out[0] == out[1]


def test_the_base_must_be_published(repo, tmp_path):
    base = sh("git", "rev-parse", "HEAD", cwd=repo)
    with pytest.raises(ValueError, match="base not published"):
        sweep.run(repo, PACK, base, store.FileStore(tmp_path / "store"), ROLES)


def test_a_variant_for_another_base_is_refused(repo, tmp_path):
    st = store.FileStore(tmp_path / "store")
    base = publish_main(repo, st)
    st.put_new(f"minimal/manifests/{IDS[0]}.json", json.dumps({"base_manifest": "m-1"}).encode())
    with pytest.raises(ValueError, match="there already, for another base"):
        sweep.run(repo, PACK, base, st, ROLES)


def test_a_pack_without_a_sweep_has_no_variants(repo, tmp_path):
    (repo / PACK / "sweeps.yaml").unlink()
    commit(repo, "no sweep")
    st = store.FileStore(tmp_path / "store")
    assert sweep.run(repo, PACK, publish_main(repo, st), st, ROLES) == []


def test_who_gets_a_variant_and_who_sees_its_status_follow_the_access_of_a_publication():
    # The toy of test_publish: the guest is granted some nodes; with `full` its read rules give every kind in
    # full by their shape (O8), so its status is derived only from rows it reads.
    from test_publish import SECRET, epoch

    roles = {"checker": "complete", "guest": "may_read"}
    assert sweep.roles_of(epoch(), roles, "node", "a") == (["checker", "guest"], ["checker"])
    assert sweep.roles_of(epoch(), roles, "node", SECRET) == (["checker"], ["checker"])
    assert sweep.roles_of(epoch(full=True), roles, "node", "a") == (["checker", "guest"], ["checker", "guest"])


def test_a_sweep_over_a_pack_with_calculation_rules_judges_access_as_a_publication(tmp_path):
    """Promote 07-11 (W12, O8): the sweep built its scope without the calculation relations, so calc__as_of
    had no kind per column and every sweep over a pack with calculation rules stopped. The relations come
    from ir/calc.json as in a publication; a hidden subject still gives no reader."""
    from test_examples import ALL, OPEN, calc_pack, publish_pack

    roles = {"checker": "complete", "viewer": "may_read"}
    e, _ = publish_pack(calc_pack(tmp_path / "all", ALL, ("a1", "open", 3), ("a2", "x", 5)), tmp_path / "all")
    assert "calc__as_of" in e.rows
    assert sweep.roles_of(e, roles, "alpha", "a1")[0] == ["checker", "viewer"]
    e, _ = publish_pack(calc_pack(tmp_path / "open", OPEN, ("a1", "open", 3), ("a2", "secret", 5)), tmp_path / "open")
    assert sweep.roles_of(e, roles, "alpha", "a1") == (["checker", "viewer"], ["checker"])
    assert sweep.roles_of(e, roles, "alpha", "a2") == (["checker"], ["checker"])


def test_variant_ids_sort_in_grid_order():
    assert publish.variant_id("x", 3, 12) == "v-x-03-12"
    assert sorted(publish.variant_id("x", i, 12) for i in (10, 2, 63, 0)) == [
        "v-x-00-12", "v-x-02-12", "v-x-10-12", "v-x-63-12"]


def test_only_a_red_variant_gets_a_diagnosis(tmp_path):
    import dataclasses

    from test_publish import epoch

    e = epoch()
    with pytest.raises(ValueError, match="only a variant"):
        publish.diagnose(e, store.FileStore(tmp_path))
    e = dataclasses.replace(e, variant={"sweep": "x", "index": 0, "value": "0"}, base_manifest="m-1")
    with pytest.raises(ValueError, match="needs a red check"):
        publish.diagnose(e, store.FileStore(tmp_path))


def test_the_shares_of_a_grid_write_together_what_one_run_writes(repo, tmp_path):
    """RV-M24: a variant of the lab is 13 s of computation, so its 64 are 13 minutes one after another,
    whatever is written. Workers each take a share of the grid; the store then holds what one run writes,
    byte for byte, whichever share ends first."""
    readable(repo)
    one, shared = store.FileStore(tmp_path / "one"), store.FileStore(tmp_path / "shared")
    base = publish_main(repo, one)
    assert publish_main(repo, shared) == base
    done = sweep.run(repo, PACK, base, one, ROLES)
    odd = sweep.run(repo, PACK, base, shared, ROLES, part=(1, 2))
    even = sweep.run(repo, PACK, base, shared, ROLES, part=(0, 2))
    assert (even, odd) == (done[0::2], done[1::2]) and len(done) == 4
    assert tree(tmp_path / "shared") == tree(tmp_path / "one")
    assert any("/explain/index.json" in key for key in tree(tmp_path / "one"))


def test_workers_side_by_side_write_what_one_process_writes(repo, tmp_path, capsys):
    """The command line with --workers: one base for all, each worker a process with its own work dir, the
    lines by variant id, and exit 1 when a worker fails."""
    readable(repo)
    profile = tmp_path / "profile.yaml"
    profile.write_text(yaml.safe_dump({"access": {"roles": ROLES}}))
    trees, printed = [], []
    for name, workers in (("one", 1), ("two", 2), ("five", 5)):  # five: more workers than grid values
        base = publish_main(repo, store.FileStore(tmp_path / name))
        args = [PACK, "--profile", str(profile), "--store", (tmp_path / name).as_uri(), "--repo", str(repo)]
        assert sweep.main([*args, "--base-commit", base, "--workers", str(workers)]) == 0
        trees.append(tree(tmp_path / name))
        printed.append(capsys.readouterr().out)
    assert trees[0] == trees[1] == trees[2] and printed[0] == printed[1] == printed[2]
    assert len(printed[0].splitlines()) == 4
    assert sweep.main([*args, "--base-commit", "0" * 40, "--workers", "2"]) == 1  # no such base: every worker fails


def test_a_worker_s_malloc_returns_what_a_variant_freed(monkeypatch):
    """Each worker starts with glibc's mmap threshold fixed (MALLOC_ENV), so a long sweep does not grow by
    the fragments of the variants before; a value the caller set wins."""
    started = []

    class Child:
        returncode = 0

        def __init__(self, argv, **kw):
            started.append(kw["env"])

        def communicate(self):
            return "", None

    monkeypatch.setattr(sweep.subprocess, "Popen", Child)
    monkeypatch.delenv("MALLOC_MMAP_THRESHOLD_", raising=False)
    monkeypatch.setenv("REZONO_PROBE", "kept")
    assert sweep.side_by_side(["pack"], 2) == (0, [])
    assert [e["MALLOC_MMAP_THRESHOLD_"] for e in started] == ["131072", "131072"]
    assert all(e["REZONO_PROBE"] == "kept" for e in started)
    started.clear()
    monkeypatch.setenv("MALLOC_MMAP_THRESHOLD_", "65536")
    sweep.side_by_side(["pack"], 1)
    assert started[0]["MALLOC_MMAP_THRESHOLD_"] == "65536"
