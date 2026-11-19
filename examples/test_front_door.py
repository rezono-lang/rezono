"""What a newcomer reads first says what is true: decisions/front-door.md and decisions/local-suppose.md.

The readme's quickstart is every `bash` block of README.md, run in order in one shell by
scripts/check-quickstart.sh; CI runs it on a clean checkout. These tests read the files themselves and run
the quickstart script on a small readme of their own, never on an example's output.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.M | re.S)


def blocks(text: str, language: str) -> list[str]:
    return [body for lang, body in FENCE.findall(text) if lang == language]


def readme() -> str:
    return README.read_text(encoding="utf-8")


class MissingNoReleaseNotice(AssertionError):
    pass


class MissingQuickstartBlocks(AssertionError):
    pass


class MissingComputingStep(AssertionError):
    pass


class MissingSupposeStep(AssertionError):
    pass


class MissingDockerfile(FileNotFoundError):
    pass


class MissingContributing(FileNotFoundError):
    pass


class MissingOracleStatus(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=MissingNoReleaseNotice, reason=(
    "extra: decisions/front-door.md: Until CHANGELOG.md has a section for a released version, README.md says "
    "\"There is no release yet.\", does not use the word released, and says how to install from a checkout. "
    "README.md only."))
def test_the_readme_names_no_release_that_is_not_there():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert not re.findall(r"^## \S", changelog, re.M), "the first release rewrites this test"
    text = readme()
    if "There is no release yet." not in text or "released" in text.lower():
        raise MissingNoReleaseNotice("README.md names a release, or does not say that there is none yet")


QUICKSTART = """# Probe

```bash
work=$(mktemp -d)
echo first > "$work/mark"
```

Not run:

```sh
exit 7
```

```bash
test "$(cat "$work/mark")" = first
echo second > "$RUNNER_TEMP/ran"
```
"""


@pytest.mark.xfail(strict=True, raises=MissingQuickstartBlocks, reason=(
    "M1: decisions/front-door.md: Let scripts/check-quickstart.sh run every bash block of README.md in order, "
    "in one shell, so a later block uses the working directory and variables of an earlier one; a block in "
    "another language, such as sh, is not run. scripts/check-quickstart.sh only."))
def test_the_quickstart_runs_every_bash_block_in_one_shell(tmp_path):
    if not (shutil.which("bash") and shutil.which("python3")):
        pytest.skip("needs bash and python3, as CI has")
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "check-quickstart.sh", tmp_path / "scripts" / "check-quickstart.sh")
    (tmp_path / "README.md").write_text(QUICKSTART, encoding="utf-8", newline="\n")
    temp = tmp_path / "runner"
    temp.mkdir()
    run = subprocess.run(["bash", "scripts/check-quickstart.sh"], cwd=tmp_path, capture_output=True, text=True,
                         env=os.environ | {"RUNNER_TEMP": str(temp)})
    if run.returncode != 0 and "Expected one Bash quickstart" in run.stderr:
        raise MissingQuickstartBlocks(run.stderr.strip())
    assert run.returncode == 0, run.stderr
    assert (temp / "ran").read_text(encoding="utf-8") == "second\n"


@pytest.mark.xfail(strict=True, raises=MissingComputingStep, reason=(
    "M1: decisions/front-door.md: Waits for examples/test_front_door.py--"
    "test_the_quickstart_runs_every_bash_block_in_one_shell. Then add a second bash block to README.md after "
    "the library step: publish examples/subsidy in the same working directory and end with a jq -e that selects "
    "one derived row and its witness. CI runs it with scripts/check-quickstart.sh. README.md only."))
def test_the_second_step_shows_a_derived_row_and_its_witness():
    steps = blocks(readme(), "bash")
    assert steps and "examples/library" in steps[0]
    if len(steps) < 2 or "examples/subsidy" not in steps[1]:
        raise MissingComputingStep("README.md has no second bash block on examples/subsidy")
    last = [line for line in steps[1].splitlines() if line.strip()][-1]
    assert last.startswith("jq -e") and "witness" in last, last


@pytest.mark.xfail(strict=True, raises=MissingSupposeStep, reason=(
    "extra: decisions/local-suppose.md: Waits for examples/test_front_door.py--"
    "test_the_second_step_shows_a_derived_row_and_its_witness and examples/subsidy/test_local_suppose.py--"
    "test_a_local_assumption_moves_the_awards_as_the_reference_does. Then add a third bash block to README.md: "
    "one assumption with rezono-suppose on the subsidy publication of the second step, and its difference. "
    "README.md only."))
def test_the_third_step_supposes_one_change():
    steps = blocks(readme(), "bash")
    if len(steps) < 3 or "rezono-suppose" not in steps[2]:
        raise MissingSupposeStep("README.md has no third bash block with rezono-suppose")
    assert "examples/subsidy" in steps[1]


def test_a_dockerfile_runs_the_quickstart_on_any_machine():
    path = ROOT / "Dockerfile"
    if not path.exists():
        raise MissingDockerfile("Dockerfile")
    froms = [line for line in path.read_text(encoding="utf-8").splitlines() if line.upper().startswith("FROM ")]
    assert froms and all(re.search(r"@sha256:[0-9a-f]{64}\b", line) for line in froms), froms
    shell = "\n".join(blocks(readme(), "sh"))
    assert "docker build" in shell and "docker run" in shell


@pytest.mark.xfail(strict=True, raises=MissingContributing, reason=(
    "extra: decisions/front-door.md: Add CONTRIBUTING.md with only what holds now: a bug as an issue with the "
    "smallest pack that shows it and a vulnerability as SECURITY.md says; the licence of the path a "
    "contribution touches, as NOTICE says; work from a fork without claiming a task branch; outside checks "
    "run after the maintainer approves them; only the maintainer sets the label planner. Link it from "
    "README.md, and say in WORKER.md that its commit identity is for the project's own agents."))
def test_contributing_says_what_holds_now():
    path = ROOT / "CONTRIBUTING.md"
    if not path.exists():
        raise MissingContributing("CONTRIBUTING.md")
    text = path.read_text(encoding="utf-8")
    for word in ("issue", "SECURITY.md", "NOTICE", "fork", "planner"):
        assert word in text, word
    assert "(CONTRIBUTING.md)" in readme()


@pytest.mark.xfail(strict=True, raises=MissingOracleStatus, reason=(
    "extra: decisions/local-suppose.md: Say in the row Change streams of docs/formal.md that the incremental "
    "oracle has no green run on main yet, with a link to the open issue. The sentence goes with the first "
    "green nightly run, and this test with it. docs/formal.md only."))
def test_change_streams_names_the_oracle_status():
    text = (ROOT / "docs" / "formal.md").read_text(encoding="utf-8")
    row, = [line for line in text.splitlines() if line.startswith("| Change streams |")]
    if "no green run" not in row:
        raise MissingOracleStatus(row)
    assert re.search(r"\]\(https://github\.com/rezono-lang/rezono/issues/\d+\)", row), row
