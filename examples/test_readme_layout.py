"""The readme shows Rezono in one screen and the output it shows is checked: decisions/front-door.md.

These tests read README.md, the files its maintainer sections move to, and the example it quotes. The quickstart
script is run on a small readme of their own, never on an example's output.
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
PARTS = ["What you get", "Example", "Try it", "Read further", "Status", "Licences and contributing"]


def readme() -> str:
    return README.read_text(encoding="utf-8")


def sections(text: str) -> list[tuple[str, str]]:
    """The `#` part and every `##` part of a readme, as (heading, body); headings inside a fence do not count."""
    parts: list[tuple[str, list[str]]] = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (line.startswith("# ") or line.startswith("## ")):
            parts.append((line.split(" ", 1)[1].strip(), []))
            continue
        if parts:
            parts[-1][1].append(line)
    return [(heading, "\n".join(body)) for heading, body in parts]


def prose(body: str) -> list[str]:
    """The non-empty lines of a part outside its fences."""
    lines, fenced = [], False
    for line in body.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.strip() and not line.startswith("### "):
            lines.append(line.strip())
    return lines


def shown_outputs(text: str) -> list[tuple[str, str | None]]:
    """Every bash block with the text block that follows it after only blank lines, or None."""
    found = list(FENCE.finditer(text))
    pairs = []
    for index, block in enumerate(found):
        if block.group(1) != "bash":
            continue
        after = found[index + 1] if index + 1 < len(found) else None
        if after and after.group(1) == "text" and not text[block.end():after.start()].strip():
            pairs.append((block.group(2), after.group(2)))
        else:
            pairs.append((block.group(2), None))
    return pairs


def stripped(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class MissingReadmeLayout(AssertionError):
    pass


class MissingReadmeExample(AssertionError):
    pass


class MissingOutputComparison(AssertionError):
    pass


class MissingMaintainerMove(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=MissingReadmeLayout, reason=(
    "extra: decisions/front-door.md: Waits for examples/test_front_door.py--test_contributing_says_what_holds_now "
    "and examples/test_readme_layout.py--test_the_quickstart_check_compares_the_shown_output. Then rewrite "
    "README.md in at most 150 lines and seven parts, in this order: # Rezono with one sentence of at most 25 words "
    "that says what the repository's About says; ## What you get, at most five lines; ## Example; ## Try it; "
    "## Read further, linking docs/tutorial.md, rezono/README.md, examples/ and docs/vision.md; ## Status, with "
    "\"There is no release yet.\"; ## Licences and contributing, two lines linking NOTICE and CONTRIBUTING.md. "
    "Make examples/test_front_door.py--test_the_second_step_shows_a_derived_row_and_its_witness and "
    "examples/test_front_door.py--test_the_readme_names_no_release_that_is_not_there green in the same pull "
    "request. README.md only."))
def test_the_readme_has_seven_parts_in_one_screen():
    text = readme()
    parts = sections(text)
    headings = [heading for heading, _ in parts]
    if not text.startswith("# Rezono\n") or headings[1:] != PARTS:
        raise MissingReadmeLayout(f"README.md has the parts {headings}, not Rezono and {PARTS}")
    assert len(text.splitlines()) <= 150, len(text.splitlines())
    body = dict(parts)

    opening = prose(parts[0][1])
    assert len(opening) == 1, opening
    assert len(re.findall(r"[.!?](?=\s|$)", opening[0])) == 1, opening[0]
    assert len(opening[0].split()) <= 25, opening[0]

    assert 1 <= len(prose(body["What you get"])) <= 5, prose(body["What you get"])
    for target in ("docs/tutorial.md", "rezono/README.md", "examples/", "docs/vision.md"):
        assert f"]({target}" in body["Read further"], target
    assert "There is no release yet." in body["Status"]
    closing = prose(body["Licences and contributing"])
    assert len(closing) == 2, closing
    assert "(NOTICE)" in closing[0] and "(CONTRIBUTING.md)" in closing[1], closing


@pytest.mark.xfail(strict=True, raises=MissingReadmeExample, reason=(
    "extra: decisions/front-door.md: Waits for examples/test_readme_layout.py--"
    "test_the_readme_has_seven_parts_in_one_screen. Then, under ## Example of README.md and before the first "
    "bash block, put three blocks from examples/subsidy: a yaml block with a few facts whose lines are lines of "
    "examples/subsidy/facts; one rule copied from a rule file of examples/subsidy or examples/subsidy-scheme; a "
    "text block with the answer and its witness, without a hash or a path, that appears word for word in the "
    "text block under the second bash block. README.md only."))
def test_the_example_answers_what_the_second_step_prints():
    text = readme()
    example = dict(sections(text)).get("Example", "")
    shown = FENCE.findall(example)
    first_bash = text.find("```bash\n")
    if len(shown) != 3 or [shown[0][0], shown[2][0]] != ["yaml", "text"] or text.find(example) > first_bash:
        raise MissingReadmeExample("README.md has no example of facts, one rule and an answer before the first command")
    (_, facts), (notation, rule), (_, answer) = shown

    fact_lines = {line for path in (ROOT / "examples" / "subsidy" / "facts").glob("*.yaml")
                  for line in stripped(path.read_text(encoding="utf-8"))}
    missing = [line for line in stripped(facts) if line not in fact_lines]
    assert not missing, missing

    excerpt = stripped(rule)
    sources = [path for folder in ("subsidy", "subsidy-scheme")
               for path in (ROOT / "examples" / folder / "rules").rglob("*") if path.is_file()]
    found = [path for path in sources if any(
        stripped(path.read_text(encoding="utf-8"))[start:start + len(excerpt)] == excerpt
        for start in range(len(stripped(path.read_text(encoding="utf-8")))))]
    assert excerpt and found, f"the {notation} rule is not copied from a rule file of examples/subsidy"
    if found[0].suffix == ".dl":
        assert rule.count(":-") == 1, rule

    assert answer.strip(), "the example shows no answer"
    assert not re.search(r"\b[0-9a-f]{64}\b|/tmp/|\$work|/store/|/manifests/", answer), answer
    pairs = shown_outputs(text)
    assert len(pairs) >= 2 and pairs[1][1] is not None, "the second step shows no output"
    assert answer in pairs[1][1], (answer, pairs[1][1])


COMPARED = """# Probe

```bash
work=$(mktemp -d)
echo first
```

```text
{first}
```

```bash
test -d "$work"
echo second
echo not compared >&2
```

```text
second
```

```bash
date +%N
```
"""


def quickstart(tmp_path: Path, first: str) -> subprocess.CompletedProcess:
    probe = tmp_path / first
    (probe / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "check-quickstart.sh", probe / "scripts" / "check-quickstart.sh")
    (probe / "README.md").write_text(COMPARED.format(first=first), encoding="utf-8", newline="\n")
    temp = probe / "runner"
    temp.mkdir()
    return subprocess.run(["bash", "scripts/check-quickstart.sh"], cwd=probe, capture_output=True, text=True,
                          env=os.environ | {"RUNNER_TEMP": str(temp)})


@pytest.mark.xfail(strict=True, raises=MissingOutputComparison, reason=(
    "extra: decisions/front-door.md: Make scripts/check-quickstart.sh run each bash block of README.md on its own, "
    "all in the same shell, and compare the standard output of a bash block with the text block that follows it "
    "after only blank lines, byte for byte. A difference fails the check and prints the expected and the actual "
    "output; standard error is not compared; a bash block without a text block is run and not compared. "
    "scripts/check-quickstart.sh only."))
def test_the_quickstart_check_compares_the_shown_output(tmp_path):
    if not (shutil.which("bash") and shutil.which("python3")):
        pytest.skip("needs bash and python3, as CI has")
    same = quickstart(tmp_path, "first")
    assert same.returncode == 0, same.stderr
    other = quickstart(tmp_path, "other")
    if other.returncode == 0:
        raise MissingOutputComparison("scripts/check-quickstart.sh accepts a text block that differs from the output")
    shown = other.stdout + other.stderr
    assert "other" in shown and "first" in shown, shown


@pytest.mark.xfail(strict=True, raises=MissingMaintainerMove, reason=(
    "extra: decisions/front-door.md: Waits for examples/test_front_door.py--test_contributing_says_what_holds_now. "
    "Then move the wheel build from README.md to rezono/README.md without naming a release, the required checks "
    "to CONTRIBUTING.md, and the Dependabot policy to SECURITY.md, so that README.md has no heading Compile an "
    "authored Rezono pack and no heading Dependency updates. README.md, rezono/README.md, CONTRIBUTING.md and "
    "SECURITY.md only."))
def test_maintainer_sections_live_beside_their_readers():
    text = readme()
    if re.search(r"^#+ (Compile an authored Rezono pack|Dependency updates)\s*$", text, re.M):
        raise MissingMaintainerMove("README.md still has a section for maintainers")
    language = (ROOT / "rezono" / "README.md").read_text(encoding="utf-8")
    assert "REZONO_PREPARED_READER" in language and "released" not in language.lower()
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for check in ("Light checks", "Inspect test evidence", "planner"):
        assert check in contributing, check
    assert "Dependabot" in (ROOT / "SECURITY.md").read_text(encoding="utf-8")
