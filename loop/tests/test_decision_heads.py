"""Every decision head follows decisions/decision-heads.md, and the decisions without one are a budget of names that
only shrinks (section 6). A decision without a head that a change adds or edits, seen against the base, is red.

With DECISION_HEADS_BASE set to a commit, the base test compares HEAD with that commit (`git diff <base>...HEAD`);
in the merge queue that is the group's base, so changes landing beside each other do not break this check.
Without it, that test is skipped and only the comparisons themselves are exercised.

The head check here is the test's own reading of sections 1 and 2, independent of loop/build_decision_capture.py.
"""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

from scripts import components

ROOT = Path(__file__).resolve().parents[2]
DECISIONS = ROOT / "decisions"
BUDGET_PATH = "loop/decision-head-budget.json"
BUDGET = ROOT / BUDGET_PATH
BASE = "DECISION_HEADS_BASE"
CEILING = 190  # the count when the budget was set; a lower budget replaces it, a higher one is a new decision
FIELDS = ("decider", "decided_on", "valid_from", "valid_until", "state", "supersedes", "subject")
REQUIRED = {"decider", "state", "subject"}
DAYS = ("decided_on", "valid_from", "valid_until")
DECIDERS = {"core", "language", "platform", "loop", "k8s-admission", "run", "owner"}
STATES = {"proposed", "in_force", "superseded", "withdrawn"}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class HeadError(ValueError):
    """A file starts a head that does not follow decisions/decision-heads.md section 1."""


def head(data: bytes) -> dict | None:
    """The fields of a decision's head, None when the file has none, or HeadError when it breaks section 1."""
    if not data.startswith(b"---\n"):
        return None
    lines = data.decode("utf-8").split("\n")
    try:
        close = lines.index("---", 1)
    except ValueError:
        raise HeadError("the head has no closing ---") from None
    if close + 2 >= len(lines) or lines[close + 1] != "" or not lines[close + 2].startswith("# ") \
            or not lines[close + 2][2:].strip():
        raise HeadError("the head is not followed by one empty line and the title line")
    fields = yaml.safe_load("\n".join(lines[1:close]))
    if not isinstance(fields, dict) or not REQUIRED <= set(fields) or not set(fields) <= set(FIELDS):
        raise HeadError(f"the head needs {sorted(REQUIRED)} and allows only {list(FIELDS)}")
    if fields["state"] not in STATES:
        raise HeadError(f"unknown state {fields['state']!r}")
    if fields["state"] != "proposed" and not {"decided_on", "valid_from"} <= set(fields):
        raise HeadError("a decision that was taken names decided_on and valid_from")
    for name in DAYS:
        if name in fields and type(fields[name]) is not datetime.date:
            raise HeadError(f"{name} is not a plain YYYY-MM-DD date")
    if "valid_until" in fields and not ("valid_from" in fields and fields["valid_from"] < fields["valid_until"]):
        raise HeadError("valid_until comes after valid_from")
    for name in ("decider", "supersedes"):
        if name in fields and (not isinstance(fields[name], list) or not fields[name]
                               or not all(isinstance(item, str) for item in fields[name])):
            raise HeadError(f"{name} is not a non-empty list")
    if not set(fields["decider"]) <= DECIDERS:
        raise HeadError(f"unknown decider in {fields['decider']}")
    if not isinstance(fields["subject"], str) or not SLUG.fullmatch(fields["subject"]):
        raise HeadError(f"the subject {fields['subject']!r} is not a slug")
    return fields


def heads(folder: Path) -> tuple[dict[str, dict], list[str]]:
    """Per decision id its head, and the sorted paths of the decisions without a head."""
    found, headless = {}, []
    for path in sorted(folder.glob("*.md")):
        if path.name == "AGENTS.md":
            continue
        data = path.read_bytes()
        try:
            fields = head(data)
        except (HeadError, UnicodeDecodeError, yaml.YAMLError) as error:
            raise HeadError(f"decisions/{path.name}: {error}") from None
        if fields is None:
            headless.append(f"decisions/{path.name}")
        else:
            found[path.stem] = fields
    for name, fields in found.items():
        unknown = set(fields.get("supersedes", ())) - set(found)
        if unknown:
            raise HeadError(f"decisions/{name}.md: supersedes {sorted(unknown)}, which have no head")
        if fields["state"] == "superseded" and not any(name in other.get("supersedes", ()) for other in found.values()):
            raise HeadError(f"decisions/{name}.md: says superseded, and no decision with a head supersedes it")
    return found, headless


def test_every_head_follows_the_decision():
    found, _ = heads(DECISIONS)
    assert "decision-heads" in found


def read_budget(text: str) -> list[str]:
    """The budget: a JSON list of decision paths, sorted, each once, written with indent 2."""
    names = json.loads(text)
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("the budget is a list of decision paths")
    if text != json.dumps(sorted(set(names)), indent=2) + "\n":
        raise ValueError("write the budget sorted, each path once, with indent 2")
    return names


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True).stdout.decode("utf-8")


def touched(root: Path, base: str) -> list[str]:
    """The decisions that HEAD adds or edits since its merge base with `base`."""
    out = git(root, "diff", "--no-renames", "--name-status", "-z", f"{base}...HEAD", "--", "decisions/")
    fields = out.split("\0")
    return sorted(path for status, path in zip(fields[0::2], fields[1::2])
                  if status in {"A", "M"} and path.endswith(".md") and path.count("/") == 1
                  and path != "decisions/AGENTS.md")


def base_budget(root: Path, base: str) -> list[str] | None:
    """The names the budget lists on the base, None when the base has no budget yet."""
    try:
        text = git(root, "show", f"{base}:{BUDGET_PATH}")
    except subprocess.CalledProcessError:
        return None
    return sorted(json.loads(text))  # a list of names, or the keys of an earlier budget with hashes


def against_the_base(root: Path, base: str) -> list[str]:
    """Each way HEAD breaks section 6 against the base: a decision without a head that it adds or edits, and a
    name that the budget gains."""
    problems = [f"{path}: added or changed without a head; give it its head"
                for path in touched(root, base) if head((root / path).read_bytes()) is None]
    before = base_budget(root, base)
    if before is not None:
        gained = sorted(set(read_budget((root / BUDGET_PATH).read_text("utf-8"))) - set(before))
        problems += [f"{BUDGET_PATH}: gains {name}; the budget only shrinks" for name in gained]
    return problems


def test_decisions_without_a_head_stay_within_the_budget():
    """Every decision without a head is listed by name. A listed decision that gains a head or goes away stays
    green; its name may go then."""
    names = read_budget(BUDGET.read_text("utf-8"))
    _, headless = heads(DECISIONS)
    assert sorted(set(headless) - set(names)) == [], "a decision without a head that the budget does not list"
    assert len(names) <= CEILING


def test_no_change_adds_or_edits_a_decision_without_a_head():
    base = os.environ.get(BASE)
    if not base:
        pytest.skip(f"{BASE} is not set; the comparison with the base runs in CI")
    git(ROOT, "rev-parse", "--verify", f"{base}^{{commit}}")  # a base that is not there fails, it does not skip
    assert against_the_base(ROOT, base) == []


def commit(root: Path, files: dict, message: str) -> str:
    for name, text in files.items():
        path = root / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    git(root, "add", "-A")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def budget_text(names: list[str]) -> str:
    return json.dumps(sorted(names), indent=2) + "\n"


def test_the_base_comparison_sees_each_change(tmp_path):
    """Against the base: a changed or a new decision without a head is red, as is a name the budget gains; an
    untouched decision without a head, one that gains a head and a name that goes are green."""
    plain = "# A decision in running text\n"
    git(tmp_path, "init", "-q")
    base = commit(tmp_path, {"decisions/plain.md": plain, "decisions/other.md": plain,
                             BUDGET_PATH: budget_text(["decisions/other.md", "decisions/plain.md"])}, "base")
    branch = git(tmp_path, "rev-parse", "--abbrev-ref", "HEAD").strip()

    def case(files: dict) -> list[str]:
        git(tmp_path, "checkout", "-q", "-f", "-B", branch, base)
        commit(tmp_path, files, "change")
        return against_the_base(tmp_path, base)

    assert case({}) == []  # the untouched decisions without a head stay green
    assert case({"decisions/plain.md": plain + "\nA changed sentence.\n"}) == [
        "decisions/plain.md: added or changed without a head; give it its head"]
    assert case({"decisions/new.md": plain}) == [
        "decisions/new.md: added or changed without a head; give it its head"]
    assert case({BUDGET_PATH: budget_text(["decisions/new.md", "decisions/other.md", "decisions/plain.md"])}) == [
        f"{BUDGET_PATH}: gains decisions/new.md; the budget only shrinks"]
    assert case({"decisions/plain.md": SATURDAY, BUDGET_PATH: budget_text(["decisions/other.md"])}) == []
    assert case({"decisions/plain.md": None}) == []  # a decision that goes away
    assert case({"decisions/saturday.md": SATURDAY}) == []  # a new decision with a head

    # In the merge queue the base is the group's base: a decision without a head that another change edited on
    # the way in is part of that base, so it does not count against this change.
    git(tmp_path, "checkout", "-q", "-f", "-B", branch, base)
    moved = commit(tmp_path, {"decisions/other.md": plain + "\nEdited by another change.\n"}, "landed beside")
    commit(tmp_path, {"decisions/saturday.md": SATURDAY}, "this change")
    assert against_the_base(tmp_path, moved) == []
    assert against_the_base(tmp_path, base) == [
        "decisions/other.md: added or changed without a head; give it its head"]


def test_the_budget_has_one_form():
    for text in ('{"decisions/a.md": "00"}\n', '[\n  "decisions/b.md",\n  "decisions/a.md"\n]\n',
                 '["decisions/a.md"]'):
        with pytest.raises(ValueError):
            read_budget(text)
    assert read_budget('[\n  "decisions/a.md"\n]\n') == ["decisions/a.md"]


SATURDAY = """---
decider: [loop, core]
decided_on: 2026-03-02
valid_from: 2026-04-01
state: in_force
subject: opening-hours
---

# Open the reading room on Saturday
"""

BROKEN = {
    "quoted-day": SATURDAY.replace("decided_on: 2026-03-02", 'decided_on: "2026-03-02"'),
    "unknown-field": SATURDAY.replace("state: in_force", "state: in_force\nowner: [loop]"),
    "no-first-day": SATURDAY.replace("valid_from: 2026-04-01\n", ""),
    "nobody-decided": SATURDAY.replace("decider: [loop, core]", "decider: []"),
    "unknown-state": SATURDAY.replace("state: in_force", "state: settled"),
    "unknown-decider": SATURDAY.replace("decider: [loop, core]", "decider: [board]"),
    "no-subject": SATURDAY.replace("subject: opening-hours\n", ""),
    "ends-before-start": SATURDAY.replace("state: in_force", "valid_until: 2026-04-01\nstate: in_force"),
    "no-title": SATURDAY.replace("# Open", "Open"),
    "no-empty-line": SATURDAY.replace("---\n\n# Open", "---\n# Open"),
    "unclosed": SATURDAY.replace("---\n\n# Open", "\n# Open"),
}


def write(folder: Path, files: dict[str, str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")


def test_the_head_check_sees_each_form(tmp_path):
    """A file with a head and one without are told apart; a broken head raises."""
    plain = "# A decision in running text\n"
    write(tmp_path / "ok", {"saturday.md": SATURDAY, "plain.md": plain, "AGENTS.md": "# Working here\n"})
    found, headless = heads(tmp_path / "ok")
    assert set(found) == {"saturday"} and headless == ["decisions/plain.md"]

    for name, text in BROKEN.items():
        write(tmp_path / name, {f"{name}.md": text})
        with pytest.raises(HeadError, match=f"decisions/{name}.md"):
            heads(tmp_path / name)

    old = SATURDAY.replace("in_force", "superseded")
    write(tmp_path / "orphan", {"old.md": old})
    with pytest.raises(HeadError, match="no decision with a head supersedes it"):
        heads(tmp_path / "orphan")
    write(tmp_path / "unknown", {"new.md": SATURDAY.replace("state: in_force", "state: in_force\nsupersedes: [old]")})
    with pytest.raises(HeadError, match="which have no head"):
        heads(tmp_path / "unknown")
    write(tmp_path / "chain", {"old.md": old, "new.md": SATURDAY.replace("state: in_force",
                                                                        "state: in_force\nsupersedes: [old]")})
    assert set(heads(tmp_path / "chain")[0]) == {"old", "new"}


def test_a_decision_change_runs_this_check():
    """The loop component reads decisions/, so a pull request that changes only a decision runs this file."""
    assert "loop" in components.shared_readers("decisions/a-new-decision.md")


def test_the_folder_guide_names_the_head():
    guide = (DECISIONS / "AGENTS.md").read_text("utf-8")
    assert "decision-heads.md" in guide
    assert [name for name in FIELDS if f"`{name}`" not in guide] == []
