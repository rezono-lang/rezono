"""One build of the slip shows every example's claim (decisions/viewer-slip.md, "Every example with a home
claim"). Generic: no pack is named. Each example pack with a home claim records by hand, in `slip.yaml` beside
its `channels.yaml`, the role, the language and the sentence its slip opens on; the page must show exactly that
sentence, and its own files must be the same bytes for every pack."""

import re
import sys
from pathlib import Path

import pytest
import yaml

EXAMPLES = Path(__file__).parent
ROOT = EXAMPLES.parent
sys.path.insert(0, str(ROOT / "tests" / "slip"))

from slip_support import MissingSlipPage, render


class MissingSlipExpectation(FileNotFoundError):
    """An example pack with a home claim has no slip.yaml, or fewer than two packs have a claim."""


def claim(channels: Path) -> list[str]:
    return ((yaml.safe_load(channels.read_text("utf-8")) or {}).get("home") or {}).get("claim") or []


PACKS = sorted(p.parent for p in EXAMPLES.rglob("channels.yaml")
               if "expected" not in p.parts and claim(p) and (p.parent / "facts").is_dir())


def normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipExpectation, MissingSlipPage, AssertionError),
    reason=(
        "Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled and tests/slip/test_slip_rule_row.py--"
        "test_slip_rule_row (the page). Also waits for the platform track: a second home claim in "
        "examples/platform whose row comes from a rule with a count over a relation the shown role reads in "
        "full, with examples/test_home_claim.py green; and for the owner of each example with a claim "
        "(examples/subsidy: language track; examples/platform: platform track) to record slip.yaml by hand "
        "beside channels.yaml: role, lang and sentence (decisions/viewer-slip.md, Every example with a home "
        "claim). Then this test needs no code beyond the page."
    ),
)
def test_one_build_every_claim(tmp_path):
    from rezono_publisher import batch, publish, store

    if len(PACKS) < 2:
        raise MissingSlipExpectation(f"{len(PACKS)} example pack(s) with a home claim; the slip needs two")
    missing = [p.relative_to(ROOT).as_posix() for p in PACKS if not (p / "slip.yaml").is_file()]
    if missing:
        raise MissingSlipExpectation("no slip.yaml in " + ", ".join(missing))
    builds = []
    for n, pack in enumerate(PACKS):
        want = yaml.safe_load((pack / "slip.yaml").read_text(encoding="utf-8"))
        assert set(want) == {"role", "lang", "sentence"}, sorted(want)
        roles = {"checker": "complete"}
        roles.setdefault(want["role"], "may_read")
        epoch = batch.epoch(pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
        target = tmp_path / str(n)
        publish.publish(epoch, store.FileStore(target), roles)
        page = render(target, want["role"], lang=want["lang"], pack=epoch.pack)
        assert normal(page["doc"].one(data_part="sentence").text()) == normal(want["sentence"]), pack.name
        builds.append(page["files"])
    assert all(files == builds[0] for files in builds), "one build of the page for every pack"
