"""G6 on `subsidy` (RV-S18): the path of a proposal, per role, up to the checked difference that role reads.

Three proposals on one published main, each through `rezono_publisher.proposal` as propose.yml runs it (the
delta on the pack at the base commit, the proposal manifest, then the difference per role):

  1  a household's size changes (`set`): both roles of the deployment get a difference, each of what it
     reads. The award moves for both; the payment against the ledger moves for `propose` only (it reads as
     the case officer), so `viewer` (the policy adviser) gets no row of the ledger, not even a count.
  2  a role is added (`insert` into `role`): that changes the closure of `may_read`, so no role gets a
     difference (rezono_publisher.difference.withheld). The proposal manifest is published as for any other.
  3  the same kind of change as 1, with a publisher that drops one changed row: the checker
     (rezono_checker.difference) refuses it, nothing of the difference is written, and the run stops (exit 2).

The gate test reads the same store (edge/gate/test/proposal-path.test.ts, REZONO_TEST_PROPOSALS): per role,
the pages of `scenario` are the difference of what the role reads in the base and the proposal, and a
proposal without a published difference is a 501. `cases.json` names the three for it, without a domain word.
Needs the compiler with DuckDB, the publisher and git.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from rezono_publisher import batch, difference, proposal, publish, store  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
PACK, NAME = "examples/subsidy", "subsidy"
SCHEME = "examples/subsidy-scheme"  # the definition the pack imports by path (RV-X35)
# The roles of the profile that publishes the pack, as the deployment has them.
ROLES = yaml.safe_load((ROOT / "deploy" / "profiles" / "edge.yaml").read_text(encoding="utf-8"))["access"]["roles"]
SIZE = {"format": "rede.delta/1", "changes": [{"op": "set", "kind": "household", "key": "H001", "slot": "persons", "value": 5}]}
ROLE = {"format": "rede.delta/1", "changes": [{"op": "insert", "file": "facts/roles.yaml", "kind": "role", "key": "auditor",
                                               "values": {"title": "Auditor"}}]}
LEDGER = ("ledger_payment", "calc__payment_difference")  # what only the case officer, so `propose`, reads


def git(*args, cwd):
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def repository(tmp: Path) -> Path:
    """A repository with the pack and the packs it imports, in one commit: main at epoch 1."""
    r = tmp / "repo"
    skip = shutil.ignore_patterns("__pycache__", "test_*.py", "expected", "golden", "diagnostics")
    shutil.copytree(HERE, r / PACK, ignore=skip)
    shutil.copytree(ROOT / SCHEME, r / SCHEME, ignore=skip)
    shutil.copytree(ROOT / "packs", r / "packs", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
    git("init", "-q", "-b", "main", cwd=r)
    git("config", "core.autocrlf", "false", cwd=r)
    git("add", ".", cwd=r)
    git("-c", "user.name=Seed", "-c", "user.email=seed@example.invalid", "commit", "-q", "-m", "base", cwd=r)
    return r


def dropping_one(real):
    """The publisher's `entries` with its first changed row left out: what the checker must refuse."""
    return lambda before, after: real(before, after)[1:]


def build(tmp: Path, root: Path) -> dict:
    """Publish main and the three proposals into the store at `root`; returns the proposal manifest ids."""
    r = repository(tmp)
    base = git("rev-parse", "HEAD", cwd=r)
    n, time = proposal.base_of(r, base)
    st = store.FileStore(root)
    publish.publish(batch.epoch(r / PACK, epoch=n, knowledge_time=time, sources=[("rules", base)]), st, ROLES)
    made = {"1": proposal.publish_proposal(r, PACK, "1", base, json.dumps(SIZE), st, ROLES),
            "2": proposal.publish_proposal(r, PACK, "2", base, json.dumps(ROLE), st, ROLES)}
    with patch.object(difference, "entries", dropping_one(difference.entries)):
        with pytest.raises(difference.Blocked, match="difference"):
            proposal.publish_proposal(r, PACK, "3", base, json.dumps(SIZE | {"changes": [SIZE["changes"][0] | {"value": 6}]}),
                                      st, ROLES)
    made["3"] = f"p-3-{n + 1}"
    cases = [{"proposal": p, "manifest": m, "difference": p == "1"} for p, m in sorted(made.items())]
    (root / "cases.json").write_text(json.dumps({"pack": NAME, "base": f"m-{n}", "cases": cases}, indent=1) + "\n",
                                     encoding="utf-8", newline="\n")
    return made


def check(root: Path, made: dict) -> None:
    """What the store holds per role; the gate test checks the answers against the role's own snapshots."""
    st = store.FileStore(root)
    index = lambda m, role: st.get(f"{NAME}/{m}/{role}/explain/index.json")  # noqa: E731
    served = sorted(r for r, how in ROLES.items() if how == "may_read")
    assert served == ["propose", "viewer"]
    for m in made.values():  # every proposal manifest is published, for every role
        assert st.get(f"{NAME}/manifests/{m}.json") is not None, m
    counts = {}
    for role in served:
        x = json.loads(index(made["1"], role))
        assert (x["manifest"], x["base_manifest"], x["role"]) == (made["1"], "m-1", role)
        counts[role] = x["difference"]["counts"]
        read = {s["relation"] for s in json.loads(st.get(f"{NAME}/manifests/{made['1']}.json"))["snapshots"] if s["role"] == role}
        assert set(counts[role]) <= read, role  # a difference only of what the role reads
        for m in (made["2"], made["3"]):  # withheld, refused: nothing of a difference, for no role
            assert index(m, role) is None and not (root / NAME / m / role / "explain").exists(), (m, role)
    assert index(made["1"], "checker") is None  # a complete role has no reader on the server: no difference
    # Both see the award move; only `propose` sees the payment against the ledger move.
    assert "calc__award" in counts["viewer"] and counts["viewer"]["calc__award"] == counts["propose"]["calc__award"]
    assert set(counts["viewer"]) < set(counts["propose"])
    assert "calc__payment_difference" in set(counts["propose"]) - set(counts["viewer"])
    assert not [rel for rel in counts["viewer"] if rel.startswith(LEDGER)], counts["viewer"]


def test_the_path_of_a_proposal_ends_in_the_difference_each_role_reads(tmp_path):
    root = tmp_path / "store"
    check(root, build(tmp_path, root))


if __name__ == "__main__":  # .github/workflows/ci.yml: the publication REZONO_TEST_PROPOSALS for the gate test
    import tempfile

    out = Path(os.environ["REZONO_TEST_PROPOSALS"])
    check(out, build(Path(tempfile.mkdtemp()), out))
    sys.exit(0)
