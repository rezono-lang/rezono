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
import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FENCE = re.compile(r"^```(\w*)\n(.*?)^```$", re.M | re.S)
PARTS = ["What you get", "Example", "Try it", "Read further", "Status", "Licences and contributing"]
LANGUAGE_FENCE = "haskell"
MAX_EXCERPT_LINES = 20
REFUSAL_CODE = "R050"
REFUSAL_DETAIL = "ambiguous leaf"
VALUE_STATES = (
    ("known", re.compile(r"\bknown\b", re.I)),
    ("unknown", re.compile(r"\bunknown\b", re.I)),
    ("not_applicable", re.compile(r"\bnot[_ ]applicable\b", re.I)),
    ("invalid", re.compile(r"\binvalid\b", re.I)),
)


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


class MissingCalculationExample(AssertionError):
    pass


class MissingCalculationQuickstartOutput(AssertionError):
    pass


def test_the_readme_has_seven_parts_in_one_screen():
    text = readme()
    parts = sections(text)
    headings = [heading for heading, _ in parts]
    if not text.startswith("# Rezono\n") or headings[1:] != PARTS:
        raise MissingReadmeLayout(f"README.md has the parts {headings}, not Rezono and {PARTS}")
    assert len(text.splitlines()) <= 180, len(text.splitlines())
    body = dict(parts)

    opening = prose(parts[0][1])
    assert len(opening) == 1, opening
    assert len(re.findall(r"[.!?](?=\s|$)", opening[0])) == 1, opening[0]
    assert len(opening[0].split()) <= 25, opening[0]

    assert 1 <= len(prose(body["What you get"])) <= 5, prose(body["What you get"])
    for link in ("](docs/tutorial.md", "](rezono/README.md", "](examples/", "](docs/vision.md"):
        assert link in body["Read further"], link
    assert "There is no release yet." in body["Status"]
    closing = prose(body["Licences and contributing"])
    assert len(closing) == 2, closing
    assert "(NOTICE)" in closing[0] and "(CONTRIBUTING.md)" in closing[1], closing


def test_the_example_answers_what_the_second_step_prints():
    text = readme()
    example = dict(sections(text)).get("Example", "")
    shown = FENCE.findall(example)
    first_bash = text.find("```bash\n")
    if len(shown) < 2 or shown[0][0] != "yaml" or shown[-1][0] != "text" or text.find(example) > first_bash:
        raise MissingReadmeExample("README.md has no example of facts and an answer before the first command")
    facts = shown[0][1]
    answer = shown[-1][1]

    fact_lines = {line for path in (ROOT / "examples" / "subsidy" / "facts").glob("*.yaml")
                  for line in stripped(path.read_text(encoding="utf-8"))}
    missing = [line for line in stripped(facts) if line not in fact_lines]
    assert not missing, missing

    assert answer.strip(), "the example shows no answer"
    assert not re.search(r"\b[0-9a-f]{64}\b|/tmp/|\$work|/store/|/manifests/", answer), answer
    pairs = shown_outputs(text)
    assert len(pairs) >= 2 and pairs[1][1] is not None, "the second step shows no output"
    assert answer in pairs[1][1], (answer, pairs[1][1])


EURO_A001 = re.compile(r"(?:€\s*|EUR\s*)2[,.]694(?:\.00|,00)?\b")


def _has_a001_and_a003(text: str) -> bool:
    return (
        "A001" in text
        and EURO_A001.search(text) is not None
        and "A003" in text
        and "unknown" in text
        and "income_statement_not_received" in text
    )


def test_the_example_shows_a001_award_and_a003_unknown():
    text = readme()
    example = dict(sections(text)).get("Example", "")
    shown = FENCE.findall(example)
    if not shown or shown[-1][0] != "text":
        raise MissingCalculationExample("README.md ## Example has no text block with the answer")
    answer = shown[-1][1]
    if not _has_a001_and_a003(example) or not _has_a001_and_a003(answer):
        raise MissingCalculationExample(
            "README.md ## Example must show A001 with its euro award and A003 as unknown "
            "(income_statement_not_received)")
    if "examples/subsidy/reference.py" not in example or "checker" not in example.lower():
        raise MissingCalculationExample(
            "README.md ## Example must state that the checker verified the witness and "
            "examples/subsidy/reference.py computes the same amount")
    assert not re.search(r"\b[0-9a-f]{64}\b|/tmp/|\$work|/store/|/manifests/", answer), answer


def test_the_second_step_prints_a001_and_a003_answers():
    text = readme()
    example = dict(sections(text)).get("Example", "")
    shown = FENCE.findall(example)
    pairs = shown_outputs(text)
    if len(pairs) < 2 or pairs[1][1] is None:
        raise MissingCalculationQuickstartOutput("README.md step 2 has no text output block")
    output = pairs[1][1]
    if not _has_a001_and_a003(output):
        raise MissingCalculationQuickstartOutput(
            "README.md step 2 text block must contain the A001 euro award and the A003 unknown "
            "(income_statement_not_received) answer")
    assert shown and shown[-1][0] == "text" and shown[-1][1] in output, (shown[-1][1], output)


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


class MissingLanguageExcerpt(AssertionError):
    pass


class MissingLanguageRefusal(AssertionError):
    pass


class MissingLanguageFourStates(AssertionError):
    pass


def declared_subsidy_rezono_sources() -> list[tuple[Path, str, Path]]:
    """Every .rezono source declared under `rezono:` in pack.yaml of examples/subsidy or its imported packs."""
    root_resolved = ROOT.resolve()
    packs_to_check: list[Path] = []
    seen: set[Path] = set()
    queue = [(ROOT / "examples" / "subsidy").resolve()]
    while queue:
        pack_dir = queue.pop(0)
        if pack_dir in seen or not (pack_dir / "pack.yaml").is_file():
            continue
        seen.add(pack_dir)
        packs_to_check.append(pack_dir)
        meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
        for entry in meta.get("imports") or []:
            raw_path = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(raw_path, str):
                continue
            target = (pack_dir / raw_path).resolve()
            if target.is_relative_to(root_resolved) and target not in seen:
                queue.append(target)

    sources: list[tuple[Path, str, Path]] = []
    for pack_dir in packs_to_check:
        meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
        for entry in meta.get("rezono") or []:
            mod_rel = entry.get("module") if isinstance(entry, dict) else None
            if not isinstance(mod_rel, str):
                continue
            mod_parts = Path(mod_rel).parts
            if "candidate" in mod_parts or mod_parts[:1] != ("rezono",) or not mod_rel.endswith(".rezono"):
                continue
            source_path = pack_dir / mod_rel
            if source_path.is_file():
                sources.append((pack_dir, source_path.relative_to(root_resolved).as_posix(), source_path))
    return sources


def matching_declared_source(excerpt: str) -> tuple[Path, str, Path] | None:
    """The declared .rezono source containing `excerpt` as a contiguous byte-for-byte slice of lines, if any."""
    excerpt_lines = excerpt.splitlines()
    if not excerpt_lines:
        return None
    count = len(excerpt_lines)
    for pack_dir, repo_rel, source_path in declared_subsidy_rezono_sources():
        source_text = source_path.read_text(encoding="utf-8")
        if excerpt not in source_text:
            continue
        source_lines = source_text.splitlines()
        if any(source_lines[i:i + count] == excerpt_lines for i in range(len(source_lines) - count + 1)):
            return pack_dir, repo_rel, source_path
    return None


def example_language_blocks(example_body: str) -> list[str]:
    return [body.rstrip("\n") for lang, body in FENCE.findall(example_body) if lang == LANGUAGE_FENCE]


def sentences(body: str) -> list[str]:
    found: list[str] = []
    for paragraph in prose(body):
        found.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip())
    return found


@pytest.mark.xfail(strict=True, raises=MissingLanguageExcerpt, reason=(
    "M3: decisions/front-door.md: Waits for examples/subsidy-scheme to replace calc/award.yaml with a "
    "declared rezono/ calculation module in pack.yaml. Then add ### The rules in Rezono inside ## Example "
    "in README.md with a <=20-line haskell fence quoting two A001 calculation rules byte for byte and a "
    "sentence linking to that source file for the other rules. README.md only."))
def test_the_readme_shows_a_literal_rezono_excerpt_of_a001_rules():
    text = readme()
    assert "rezono 1" not in text.lower(), "README.md must not mention rezono 1 while the quoted pack is in rezono 0"
    example = dict(sections(text)).get("Example", "")
    if not re.search(r"^###\s+The rules in Rezono\s*$", example, re.M):
        raise MissingLanguageExcerpt("README.md ## Example has no ### The rules in Rezono subsection")
    blocks = example_language_blocks(example)
    if not blocks:
        raise MissingLanguageExcerpt(
            f"README.md ## Example has no {LANGUAGE_FENCE} fence with the Rezono calculation excerpt")
    excerpt = blocks[0]
    lines = excerpt.splitlines()
    if not lines or len(lines) > MAX_EXCERPT_LINES:
        raise MissingLanguageExcerpt(
            f"README.md Rezono excerpt has {len(lines)} lines, expected 1..{MAX_EXCERPT_LINES}")
    matched = matching_declared_source(excerpt)
    if matched is None:
        raise MissingLanguageExcerpt(
            "README.md Rezono excerpt does not match byte for byte any rezono/ source declared in pack.yaml of "
            "examples/subsidy or a pack it imports")
    _, repo_rel, _ = matched
    shown = FENCE.findall(example)
    assert shown and shown[-1][0] == "text", "README.md ## Example must end with the text answer block"
    answer = shown[-1][1]
    rules = re.findall(r"^\s*derived\s+([a-z][a-z0-9_]*)\b", excerpt, re.M)
    assert len(rules) == 2, f"expected two calculation rules in the excerpt, found {rules}"
    for rule in rules:
        assert f"rule {rule}" in answer, f"calculation rule {rule!r} from the excerpt is missing from the text block"
    example_prose = "\n".join(prose(example))
    assert f"]({repo_rel})" in example_prose, (
        f"README.md ## Example must link to {repo_rel} for the remaining calculation rules")


@pytest.mark.xfail(strict=True, raises=MissingLanguageRefusal, reason=(
    "M3: decisions/front-door.md: Waits for examples/subsidy-scheme to replace calc/award.yaml with a "
    "declared rezono/ calculation module in pack.yaml. Then show the excerpt with one changed line "
    "(Application.advice_allowance -> advice_allowance) in a second haskell block in ## Example beside its "
    "R050 ambiguous leaf compiler refusal. README.md only."))
def test_the_readme_changed_excerpt_is_refused_by_the_compiler(tmp_path):
    text = readme()
    example = dict(sections(text)).get("Example", "")
    blocks = example_language_blocks(example)
    if len(blocks) < 2:
        raise MissingLanguageRefusal(
            f"README.md ## Example needs a second {LANGUAGE_FENCE} fence showing the one-line change")
    excerpt, modified = blocks[0], blocks[1]
    example_prose = "\n".join(prose(example))
    if REFUSAL_CODE not in example_prose:
        raise MissingLanguageRefusal(
            f"README.md ## Example must name the compiler refusal code {REFUSAL_CODE}")
    matched = matching_declared_source(excerpt)
    if matched is None:
        raise MissingLanguageRefusal(
            "README.md Rezono excerpt does not match a declared rezono/ source of examples/subsidy or an import")
    pack_dir, _, source_path = matched

    orig_lines, mod_lines = excerpt.splitlines(), modified.splitlines()
    assert len(orig_lines) == len(mod_lines), (len(orig_lines), len(mod_lines))
    diffs = [(before, after) for before, after in zip(orig_lines, mod_lines) if before != after]
    assert len(diffs) == 1, f"modified excerpt must differ on exactly one line, found {len(diffs)}: {diffs}"

    from rezono_compiler import emit, pack

    root_resolved = ROOT.resolve()
    shutil.copytree(ROOT / "packs", tmp_path / "packs", ignore=shutil.ignore_patterns("candidate"))
    pack_rel = pack_dir.relative_to(root_resolved)
    copied_pack = tmp_path / pack_rel
    shutil.copytree(pack_dir, copied_pack, ignore=shutil.ignore_patterns("candidate"))
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
    for entry in meta.get("imports") or []:
        raw_path = entry.get("path") if isinstance(entry, dict) else None
        if not isinstance(raw_path, str):
            continue
        imp_dir = (pack_dir / raw_path).resolve()
        if imp_dir.parent == (ROOT / "examples").resolve():
            imp_rel = imp_dir.relative_to(root_resolved)
            if not (tmp_path / imp_rel).exists():
                shutil.copytree(imp_dir, tmp_path / imp_rel, ignore=shutil.ignore_patterns("candidate"))

    copied_source = copied_pack / source_path.relative_to(pack_dir)
    source_text = copied_source.read_text(encoding="utf-8")
    assert source_text.count(excerpt) == 1, f"expected excerpt once in {copied_source}"
    copied_source.write_text(source_text.replace(excerpt, modified, 1), encoding="utf-8", newline="\n")

    with pytest.raises(pack.CompileError) as caught:
        emit.compile_pack(pack.read(copied_pack))
    error = caught.value
    codes = [d.code for d in getattr(error, "diagnostics", ())]
    assert REFUSAL_CODE in codes or REFUSAL_CODE in str(error), str(error)
    assert REFUSAL_DETAIL in str(error), str(error)


@pytest.mark.xfail(strict=True, raises=MissingLanguageFourStates, reason=(
    "M3: decisions/front-door.md: Waits for examples/subsidy-scheme to replace calc/award.yaml with a "
    "declared rezono/ calculation module in pack.yaml. Then add one sentence in ## Example of README.md "
    "naming the four value states (known, unknown, not_applicable, invalid). README.md only."))
def test_the_readme_names_the_four_value_states_in_one_sentence():
    example = dict(sections(readme())).get("Example", "")
    found = [
        sentence for sentence in sentences(example)
        if all(pattern.search(sentence) for _, pattern in VALUE_STATES)
    ]
    if not found:
        names = ", ".join(name for name, _ in VALUE_STATES)
        raise MissingLanguageFourStates(
            f"README.md ## Example needs one sentence naming all four value states ({names})")
