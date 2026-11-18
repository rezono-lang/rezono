"""The manifest of a proposal: after the pull request is open, the delta
on the pack at its base commit, as one epoch, published per role next to the main manifests.

  python -m rezono_publisher.proposal PACK --profile deploy/profiles/edge.yaml --proposal <id> \
      --base-commit <sha> --delta-env DELTA --co-author "<subject> <address>" --proposed-at <UTC instant> \
      [--repo .] [--store file:///data]

Everything comes from Git and the inputs, never from the clock or the branch:
- the base manifest is `m-<number of commits up to the base commit>`, the rule of publish.sh, and it must be
  published already ("base not published" otherwise);
- the epoch is the base's plus one, the knowledge time the base commit's time, the source `rules=<base>`;
- the facts are the canonical writer's output for the delta on the pack at the base commit, in a private
  work dir (git worktree), so no code or file of the proposal branch is read. The job runs main's code;
- the origin of a value the delta writes in a fact file with a source companion is the verified proposer at
  the instant the gate took the proposal (`--co-author`, `--proposed-at`). A proposal is of whoever
  wrote it first, so the job passes the two the proposal's commit records, as `rezono_githost.propose`
  read them from the head of the proposal branch (its `--stated-out` file), not those of the dispatch that
  happens to run: the manifest's facts and sources are the bytes of the branch, also for a repeat by someone
  else. This command reads no branch itself. Without both it refuses before it reads anything.

The manifest is `<pack>/manifests/p-<id>-<epoch>.json` and its files `<pack>/p-<id>-<epoch>/<role>/…`.
A manifest that is there already is kept: a repeat of the same proposal is a no-op.
The delta comes from an environment variable, never from the command line.

Exit 0: published or already there (prints the manifest id). Exit 2: a red check, nothing written.
Exit 1: an error, such as an unpublished base.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import difference, pointers, publish, store
from .__main__ import profile_settings

COMMIT = re.compile(r"^[0-9a-f]{40}$")
MAX_DELTA = 1 << 20  # bytes: a delta from the viewer is small; anything larger is refused before it is read
PROPOSAL = re.compile(r"^[1-9][0-9]*$")
PERSON = re.compile(r"^\s*([^<>]+?)\s*<[^<>\s]+@[^<>\s]+>\s*$")  # as rezono_githost.propose reads the same input


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def base_of(repo: Path, base_commit: str) -> tuple[int, str]:
    """The epoch and knowledge time of the main manifest at a commit, as publish.sh computes them."""
    return int(git(repo, "rev-list", "--count", base_commit)), git(repo, "log", "-1", "--format=%cI", base_commit)


def pack_name(pack_dir: Path) -> str:
    import yaml

    return yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8"))["name"]


def same_source(manifest: dict, mid: str, epoch: int, commit: str) -> bool:
    """The manifest is the one expected: its id, its epoch and the commit of its rules."""
    sources = {s.get("source_id"): s.get("position") for s in manifest.get("sources", []) if isinstance(s, dict)}
    return manifest.get("id") == mid and manifest.get("epoch") == epoch and sources.get("rules") == commit


def stated_by(co_author: str, proposed_at: str) -> dict:
    """The origin of what a proposal writes: its verified proposer, at the instant the gate took it."""
    from rezono_compiler import source_writer

    m = PERSON.match(co_author)
    if not m or not proposed_at:
        raise ValueError("a proposal needs its verified proposer '<subject> <address>' and the instant it was "
                         "proposed (--co-author, --proposed-at); nothing changed")
    return source_writer.stated(m.group(1), proposed_at)


def publish_proposal(repo: Path, pack: str, proposal: str, base_commit: str, delta_text: str, st, roles: dict,
                     stated: dict | None = None) -> str:
    """`stated` is the origin of the rows the delta writes in a fact file with a source companion
    (`stated_by`); without it the writer refuses such a row, and nothing is published."""
    from rezono_compiler import writer

    from . import batch

    if not PROPOSAL.match(proposal):
        raise ValueError(f"a proposal id is a positive whole number as text, not {proposal!r}")
    if not COMMIT.match(base_commit):
        raise ValueError("the base commit is 40 lower-case hex digits")
    if len(delta_text.encode("utf-8")) > MAX_DELTA:
        raise ValueError(f"the delta is larger than {MAX_DELTA} bytes")
    n, knowledge_time = base_of(repo, base_commit)
    work = Path(tempfile.mkdtemp(prefix=writer.WORK_PREFIX))
    try:
        git(repo, "worktree", "add", "-q", "--detach", str(work / "repo"), base_commit)
        pack_dir = work / "repo" / pack
        if (work / "repo").resolve() not in pack_dir.resolve().parents:
            raise ValueError(f"the pack must be a directory inside the repository, not {pack!r}")
        name = pack_name(pack_dir)
        base = st.get(f"{name}/manifests/m-{n}.json")
        if base is None:
            raise ValueError(f"base not published: {name}/manifests/m-{n}.json")
        if not same_source(json.loads(base), f"m-{n}", n, base_commit):
            raise ValueError(f"the published m-{n} is not of commit {base_commit}: another commit with as many ancestors")
        mid = f"p-{proposal}-{n + 1}"
        there = st.get(f"{name}/manifests/{mid}.json")
        if there is not None:
            done = json.loads(there)
            if done.get("base_manifest") != f"m-{n}" or not same_source(done, mid, n + 1, base_commit):
                raise ValueError(f"{mid} is published already, for another base")
            # A run that stopped between the manifest and its pointer: the pointer from the kept bytes.
            pointers.write(st, name, "manifests", there)
            difference.publish(st, name, mid, json.loads(delta_text))  # a stopped run's: same bytes
            return mid
        texts, _ = writer.apply_delta(pack_dir, json.loads(delta_text), stated=stated)
        if not texts:
            raise ValueError("the delta changes nothing")
        writer.write_files(pack_dir, texts)
        e = batch.epoch(pack_dir, epoch=n + 1, knowledge_time=knowledge_time, sources=[("rules", base_commit)],
                        proposal=proposal, base_manifest=f"m-{n}")
        mid = publish.publish(e, st, roles)["id"]
        difference.publish(st, name, mid, json.loads(delta_text))  # what `suppose` reads (R10 step 7)
        return mid
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(work / "repo")], cwd=repo, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m rezono_publisher.proposal")
    p.add_argument("pack")
    p.add_argument("--profile", required=True)
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    p.add_argument("--proposal", required=True, help="the id of the pull request")
    p.add_argument("--base-commit", required=True)
    p.add_argument("--delta-env", required=True, help="environment variable that holds the delta (JSON)")
    p.add_argument("--repo", default=".")
    p.add_argument("--co-author", default="", help="the verified proposer, as the proposal's commit records it: "
                                                   "<subject> <address that reaches no one>")
    p.add_argument("--proposed-at", default="", help="the instant the gate took the proposal, as the proposal's "
                                                     "commit records it: 2026-11-10T21:03:11Z")
    args = p.parse_args(argv)
    from rezono_compiler import writer

    try:
        stated = stated_by(args.co_author, args.proposed_at)  # before the profile and the store
        url, endpoint, roles = profile_settings(args.profile)
        mid = publish_proposal(Path(args.repo).resolve(), args.pack, args.proposal, args.base_commit,
                               os.environ.get(args.delta_env, ""), store.open_store(args.store or url, endpoint), roles,
                               stated)
    except (publish.Blocked, difference.Blocked) as err:
        print(f"blocked: {err}", file=sys.stderr)
        return 2
    except (store.Conflict, ValueError, writer.WriteError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(mid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
