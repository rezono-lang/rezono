"""Every decision head follows decisions/decision-heads.md, and the decisions without one are a budget that only goes
down (section 6). A new decision without a head, or a decision whose text changes while it has none, is red.

The head check here is the test's own reading of sections 1 and 2, independent of loop/build_decision_capture.py.
"""
import datetime
import hashlib
import json
from pathlib import Path
import re

import pytest
import yaml

from scripts import components

ROOT = Path(__file__).resolve().parents[2]
DECISIONS = ROOT / "decisions"
BUDGET = ROOT / "loop" / "decision-head-budget.json"
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


def heads(folder: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Per decision id its head, and per path of a decision without a head the SHA-256 of its bytes."""
    found, headless = {}, {}
    for path in sorted(folder.glob("*.md")):
        if path.name == "AGENTS.md":
            continue
        data = path.read_bytes()
        try:
            fields = head(data)
        except (HeadError, UnicodeDecodeError, yaml.YAMLError) as error:
            raise HeadError(f"decisions/{path.name}: {error}") from None
        if fields is None:
            headless[f"decisions/{path.name}"] = hashlib.sha256(data).hexdigest()
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


def outside(headless: dict[str, str], budget: dict[str, str]) -> list[str]:
    """The decisions without a head that the budget does not list with these exact bytes: new or changed ones."""
    return sorted(path for path, digest in headless.items() if budget.get(path) != digest)


def test_decisions_without_a_head_stay_within_the_budget():
    """The budget is an upper bound per file: a decision without a head must be listed with its exact bytes, so a
    new or changed one is red. A listed decision that gains a head or goes away stays green; its line may go then."""
    text = BUDGET.read_text("utf-8")
    budget = json.loads(text)
    assert text == json.dumps(budget, indent=2, sort_keys=True) + "\n", "write the budget sorted, with indent 2"
    _, headless = heads(DECISIONS)
    assert outside(headless, budget) == [], "new or changed without a head; give each its head"
    assert len(budget) <= CEILING


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
    """The budget can fail: a new, a changed and a broken decision each break it; a head or removal does not."""
    plain = "# A decision in running text\n"
    write(tmp_path / "ok", {"saturday.md": SATURDAY, "plain.md": plain, "AGENTS.md": "# Working here\n"})
    found, headless = heads(tmp_path / "ok")
    assert set(found) == {"saturday"} and set(headless) == {"decisions/plain.md"}
    budget = dict(headless)

    write(tmp_path / "ok", {"new.md": plain})
    assert outside(heads(tmp_path / "ok")[1], budget) == ["decisions/new.md"]  # new, without a head
    (tmp_path / "ok" / "new.md").unlink()
    write(tmp_path / "ok", {"plain.md": plain + "\nA changed sentence.\n"})
    assert outside(heads(tmp_path / "ok")[1], budget) == ["decisions/plain.md"]  # changed, no head
    write(tmp_path / "ok", {"plain.md": SATURDAY.replace("Saturday", "weekdays")})
    assert heads(tmp_path / "ok")[1] == {} and outside({}, budget) == []  # given a head, still green

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
