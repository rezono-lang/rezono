"""A pack with two sweeps publishes the variants of each, the local reader lists both, and `sweep` answers each by
name, in the REPL too (decisions/viewer-slip.md, "Several sweeps").

tests/fixtures/slip sweeps the amount of item-a; a second sweep moves the amount of item-b. Both grids come from
the slot's `explore` (0 to 30 by 5). At 30 the invariant too_large fails, so the last stop is red; every other
stop is green for `reader`, who reads every relation in full. Written here by hand.
"""

import os
import re
import subprocess

import pytest
from slip_support import PACK, ROOT, add_sweep, ask, node, publish_sweeps


class MissingSeveralSweeps(AssertionError):
    """The pack, the publisher, the local reader or the REPL still takes one sweep only."""


VALUES = [str(v) for v in range(0, 31, 5)]
STATUSES = ["green"] * 6 + ["red"]
NAMES = ["item_amount", "item_b_amount"]


def published(tmp_path):
    try:
        return publish_sweeps(tmp_path, change=lambda pack: add_sweep(pack, "item_b_amount", "item-b"))
    except Exception as error:  # the compiler refuses a second sweep, or the publisher cannot run it
        raise MissingSeveralSweeps(f"{type(error).__name__}: {error}"[:400]) from error


def test_several_sweeps(tmp_path):
    store, manifest, done = published(tmp_path)
    variants = {vid for vid, _ in done}
    for name in NAMES:
        assert {vid for vid in variants if vid.startswith(f"v-{name}-")}, name
    [listing, *answers] = ask(store, "reader", f"/{PACK}/sweeps?m={manifest['id']}",
                              *(f"/{PACK}/{manifest['id']}/ask/sweep?sweep={name}" for name in NAMES))
    if listing["status"] != 200 or [s["name"] for s in listing["body"]["sweeps"]] != NAMES:
        raise MissingSeveralSweeps(f"GET /{PACK}/sweeps: {listing}"[:400])
    for sweep in listing["body"]["sweeps"]:
        assert [c["value"] for c in sweep["cells"]] == VALUES
        assert [c["status"] for c in sweep["cells"]] == STATUSES
    for name, answer in zip(NAMES, answers):
        assert answer["status"] == 200, answer
        assert answer["body"]["delta"] == {"kind": "sweep", "id": name}
        assert [c["value"] for c in answer["body"]["series"]] == VALUES


def test_several_sweeps_in_the_repl(tmp_path):
    store, _, _ = published(tmp_path)
    run = subprocess.run([node(), str(ROOT / "tools" / "repl" / "src" / "main.ts"), "--store", store.as_posix(),
                          "--role", "reader"], input=f":use {PACK} latest\n:sweep item_b_amount\n",
                         capture_output=True, encoding="utf-8", timeout=120, cwd=ROOT, env=dict(os.environ))
    assert run.returncode == 0, run.stderr
    rows = [line.split() for line in run.stdout.splitlines() if re.match(r"^\d+\s+-?\d+\s+[a-z_]+\s", line)]
    if not rows:
        raise MissingSeveralSweeps(run.stdout[-400:])
    assert [(r[0], r[1], r[2]) for r in rows] == [(str(i), v, s) for i, (v, s) in enumerate(zip(VALUES, STATUSES))]
    assert all(r[3].startswith("v-item_b_amount-") for r in rows[:6])
