"""Sweep v1 (docs/interaction.md, section 1): after main's manifest m-N, one epoch per grid value of the pack's
sweep, each published as a variant against m-N.

  python -m rezono_publisher.sweep PACK --profile deploy/profiles/edge.yaml (--base-commit <sha> | --newest) \
      [--repo .] [--store file:///data] [--workers N]

With --workers N, N processes compute the variants side by side, each a share of the grid (side_by_side;
sweep.sh asks for two). The store then holds what one process writes: a variant's bytes depend on its base
and its value alone. A variant of the lab is 13 s of computation, so its 64 are 13 minutes one after
another, whatever is written.

With --newest the base is the pack's newest main manifest, at the commit it names: what publish.sh left as
main, also when it found the pack unchanged and published nothing for HEAD.

- The grid comes from the compiler (`sweeps.yaml` and the slot's `explore`). Each value is one delta `set` on
  main's facts at the base commit, in a private work dir (git worktree), in grid order. The epoch is N + 1, the
  knowledge time and the source those of m-N, as for a proposal.
- A green value becomes the variant manifest `<pack>/manifests/v-<sweep>-<ii>-<N+1>.json` with base_manifest
  m-N. A red value (a red check) becomes the diagnosis `<pack>/diagnoses/v-<sweep>-<ii>-<N+1>.json`. A red
  variant never blocks main: m-N is published before the first variant is computed.
- Any other error (a crash, a checker failure, a conflict in the store) stops the run with exit 1.
- A variant that is there already is kept, so a run that stopped (a timeout) is completed by the next one.
  A kept variant whose differences are there too costs a lookup: nothing is made or written again.
  A variant that is not there is "not computed": never red, never green.
- Each variant writes only what differs from m-N (publish.plan with `base`): every other snapshot, witness set
  and compiled file of a variant is m-N's own object for the same role, with the same bytes. So a variant
  costs the objects the swept cell changes, not a whole publication (measured on the lab: 30 of 516).
- Roles: `readers` may read the swept cell; only they get the variant. `status_readers` also
  read every row, so a variant's status tells them nothing they cannot see; the others see `unavailable`.
  The gate removes both lists before it serves a variant.

Exit 0: every variant is there (one line per variant: id and what happened). Exit 1: an error.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import access, difference, pointers, publish, store, timing
from .cache import SweepStore
from .__main__ import profile_settings
from .proposal import COMMIT, base_of, git, pack_name, same_source


def grid(sweep: dict) -> list[int]:
    return [sweep["min"] + i * sweep["step"] for i in range(sweep["count"])]


def roles_of(e: publish.Epoch, roles: dict[str, str], kind: str, key: str) -> tuple[list[str], list[str]]:
    """Who gets the variant and who sees its status, with the access semantics of a publication (O7, O8).

    A reader may read the swept element (kind, key). A status reader reads every relation in full: by the
    shape of its read rules, never by the data, so whether a role sees the status tells nothing about a row
    it may not read. Every other reader sees `unavailable` (the gate does that).
    """
    doc = json.loads(e.rules)
    columns = access.with_calc(e.columns, publish.calc_ir(e))  # as a publication sees them
    readers, status_readers = [], []
    for role, mode in sorted(roles.items()):
        if mode == access.COMPLETE:
            readers.append(role)
            status_readers.append(role)
            continue
        if mode != access.FILTERED:
            raise ValueError(f"role {role}: unknown access {mode!r}")
        try:
            scope = access.Scope(e.rows, e.kinds, e.parents, columns, doc, role)
        except access.Uncovered as err:
            raise publish.Blocked(f"{publish.ACCESS_CHECK}: {err}") from err
        if not scope.reads(kind, key):
            continue
        readers.append(role)
        if scope.full >= set(e.rows):
            status_readers.append(role)
    return readers, status_readers


def change_of(sw: dict) -> dict:
    """The change a variant makes, without its value: what decides whether a right may change (difference.withheld)."""
    return {"op": "set", "kind": sw["kind"], "key": sw["key"], "slot": sw["slot"]}


def kept(st, pack: str, vid: str, base: str) -> str | None:
    """'manifest' or 'diagnosis' if the variant is there already, for the same base; None if not."""
    for what, kind, field in (("manifest", "manifests", "base_manifest"), ("diagnosis", "diagnoses", "last_good_manifest")):
        data = st.get(f"{pack}/{kind}/{vid}.json")
        if data is not None:
            if json.loads(data).get(field) != base:
                raise ValueError(f"{vid} is there already, for another base")
            # A run that stopped between the object and its pointer: the pointer from the kept bytes.
            pointers.write(st, pack, kind, data)
            return what
    return None


def explained(st, pack: str, vid: str, main: dict) -> bool:
    """True when the differences of a kept variant are all there: the index of every role the gate serves in
    the variant and in its base (the roles of difference.plan). The indexes are written after every piece of
    every role (difference.publish), so together they say the pieces are there; a run that stopped anywhere
    before them finds one missing and makes the differences again. False also where there is no index to
    find (no such role, or a delta that may change a right): making nothing again costs little."""
    m = json.loads(st.get(f"{pack}/manifests/{vid}.json"))
    served = {s["role"] for s in m["snapshots"] if s.get("complete") is False}
    served &= {s["role"] for s in main["snapshots"] if s.get("complete") is False}
    return bool(served) and all(st.get(f"{pack}/{vid}/{role}/explain/index.json") is not None
                                for role in sorted(served))


def _io(st, before):
    return " ".join(f"{k}={v - before[k]}" for k, v in st.counts().items())


@contextmanager
def _phase(st, label, name):
    start = time.monotonic()
    before = st.counts()
    print(f"sweep {label} {name} start", file=sys.stderr, flush=True)
    try:
        yield
    finally:
        print(f"sweep {label} {name} {time.monotonic() - start:.3f}s {_io(st, before)}",
              file=sys.stderr, flush=True)


def _difference(st, name, vid, change, label):
    with _phase(st, label, "difference"):
        difference.publish(st, name, vid, {"changes": [change]})


def newest_commit(repo: Path, pack: str, st) -> str:
    """The commit of the pack's newest main manifest (its `rules` source): the base of `--newest`."""
    head = publish.newest_main(st, pack_name(repo / pack))
    if head is None:
        raise ValueError(f"base not published: {pack} has no main manifest")
    sources = {s.get("source_id"): s.get("position") for s in head.get("sources", []) if isinstance(s, dict)}
    commit = sources.get("rules")
    if not isinstance(commit, str) or not COMMIT.match(commit):
        raise ValueError(f"the newest main manifest {head.get('id')} names no commit as its rules")
    return commit


# glibc's malloc serves a block of this size or more with its own mmap, returned to the system when freed.
# Its default threshold is dynamic: each freed mmapped block raises it (up to 32 MiB), so later blocks of
# that size come from the heap, where a variant's freed blocks stay as fragments. The pilot's workers grew by
# about 30 MiB per variant on Linux. A lab worker's live heap stays at 91 MiB over 16 variants while malloc's
# free memory grows from 235 to 396 MiB (resident 607 -> 756 MiB); with the threshold fixed at glibc's
# initial 128 KiB the free memory stays at 82-85 MiB (resident 489 -> 540 MiB) and the run is no slower
# (16-11-2026). Other platforms ignore the variable.
MALLOC_ENV = {"MALLOC_MMAP_THRESHOLD_": str(128 * 1024)}


def side_by_side(argv: list[str], workers: int) -> tuple[int, list[str]]:
    """The sweep `argv` names, by `workers` processes at once: (exit code, the lines of all, by variant id).

    Worker i takes the grid values whose index is i modulo `workers` (`--part`), in a work dir and with a
    cache of its own. A variant is a function of its base and its value, it writes only keys of its own, and
    every object is written once (store.put_new). So the store holds afterwards what one process writes,
    whatever the number of workers and the order they end in. The base is the caller's, one for all: a worker
    never looks up the newest main manifest itself. A worker's malloc returns what a variant freed
    (MALLOC_ENV), unless the caller set the variable itself."""
    env = MALLOC_ENV | dict(os.environ)
    children = [subprocess.Popen([sys.executable, "-m", "rezono_publisher.sweep", *argv, "--part", f"{i}/{workers}"],
                                 stdout=subprocess.PIPE, text=True, env=env) for i in range(workers)]
    lines = [line for child in children for line in child.communicate()[0].splitlines()]
    return (1 if any(child.returncode for child in children) else 0), sorted(lines)


def run(repo: Path, pack: str, base_commit: str, st, roles: dict[str, str],
        part: tuple[int, int] = (0, 1)) -> list[tuple[str, str]]:
    """The variants of the pack's sweeps against the main manifest of `base_commit`: [(variant id, what
    happened)]. `part` (i, n): only the grid values whose index is i modulo n (side_by_side)."""
    from rezono_compiler import pack as packs
    from rezono_compiler import writer

    from . import batch

    if not COMMIT.match(base_commit):
        raise ValueError("the base commit is 40 lower-case hex digits")
    if not roles:
        raise ValueError("no roles: nothing would be readable")
    n, knowledge_time = base_of(repo, base_commit)
    base = f"m-{n}"
    work = Path(tempfile.mkdtemp(prefix=writer.WORK_PREFIX))
    done = []
    try:
        git(repo, "worktree", "add", "-q", "--detach", str(work / "repo"), base_commit)
        pack_dir = work / "repo" / pack
        if (work / "repo").resolve() not in pack_dir.resolve().parents:
            raise ValueError(f"the pack must be a directory inside the repository, not {pack!r}")
        model = packs.read(pack_dir)
        name = model.meta["name"]
        st = SweepStore(st, name, base)
        published = st.get(f"{name}/manifests/{base}.json")
        if published is None:
            raise ValueError(f"base not published: {name}/manifests/{base}.json")
        main = json.loads(published)
        if not same_source(main, base, n, base_commit):
            raise ValueError(f"the published {base} is not of commit {base_commit}: another commit with as many ancestors")
        for sw in model.sweeps:
            for i, value in enumerate(grid(sw)):
                if i % part[1] != part[0]:
                    continue  # another worker's value
                vid = publish.variant_id(sw["name"], i, n + 1)
                label = f"{pack}/{vid}"
                before = st.begin(vid)
                print(f"sweep {label} start", file=sys.stderr, flush=True)
                timing.switch("lookup")
                result = "error"
                try:
                    with _phase(st, label, "lookup"):
                        there = kept(st, name, vid, base)
                    if there:
                        # A run that stopped before the difference: made again, the same bytes. One that is
                        # whole costs its lookup, so a sweep with nothing to compute writes nothing.
                        if there == "manifest" and not explained(st, name, vid, main):
                            _difference(st, name, vid, change_of(sw), label)
                        result = f"{there} kept"
                    else:
                        change = {"op": "set", "kind": sw["kind"], "key": sw["key"], "slot": sw["slot"], "value": value}
                        texts, _ = writer.apply_delta(pack_dir, {"format": writer.FORMAT, "changes": [change]})
                        originals = {f: writer.read_fact_file(pack_dir, f) for f in texts}
                        writer.write_files(pack_dir, texts)
                        try:
                            with _phase(st, label, "epoch"):
                                e = batch.epoch(pack_dir, epoch=n + 1, knowledge_time=knowledge_time,
                                                sources=[("rules", base_commit)], base_manifest=base)
                        finally:
                            writer.write_files(pack_dir, originals)  # the next value starts from main's facts again
                        readers, status_readers = roles_of(e, roles, sw["kind"], sw["key"])
                        e = dataclasses.replace(e, variant={"sweep": sw["name"], "index": i, "value": str(value),
                                                            "readers": readers, "status_readers": status_readers})
                        if any(c["status"] == "red" for c in e.checks):
                            publish.diagnose(e, st)
                            result = "diagnosis"
                        else:
                            with _phase(st, label, "publication"):
                                publish.publish(e, st, {r: roles[r] for r in readers}, base=main)
                            _difference(st, name, vid, change, label)
                            result = "manifest"
                    done.append((vid, result))
                finally:
                    timing.report(label, out=sys.stderr)
                    print(f"sweep {label} {result} {_io(st, before)}", file=sys.stderr, flush=True)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(work / "repo")], cwd=repo, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    return done


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m rezono_publisher.sweep")
    p.add_argument("pack")
    p.add_argument("--profile", required=True)
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    base = p.add_mutually_exclusive_group(required=True)
    base.add_argument("--base-commit", help="the commit of the main manifest the variants vary")
    base.add_argument("--newest", action="store_true",
                      help="vary the pack's newest main manifest, at the commit it names")
    p.add_argument("--repo", default=".")
    p.add_argument("--workers", type=int, default=1, help="variants side by side: this many processes")
    p.add_argument("--part", default="0/1", help=argparse.SUPPRESS)  # I/N: a worker's share of the grid
    args = p.parse_args(argv)
    from rezono_compiler import writer

    url, endpoint, roles = profile_settings(args.profile)
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    part = tuple(int(x) for x in args.part.split("/"))
    if args.workers < 1 or len(part) != 2 or not 0 <= part[0] < part[1]:
        p.error("--workers is 1 or more, and --part is I/N with 0 <= I < N")
    try:
        repo, st = Path(args.repo).resolve(), store.open_store(url, endpoint)
        commit = args.base_commit or newest_commit(repo, args.pack, st)
        if args.workers > 1:
            code, lines = side_by_side([args.pack, "--profile", args.profile, "--base-commit", commit, "--repo",
                                        str(repo), *(["--store", args.store] if args.store else [])], args.workers)
            for line in lines:
                print(line)
            return code
        done = run(repo, args.pack, commit, st, roles, part)
    except (publish.Blocked, difference.Blocked, store.Conflict, ValueError, writer.WriteError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    for vid, what in done:
        print(vid, what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
