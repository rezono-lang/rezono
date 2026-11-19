"""Read the head of each decision file as one std-decision row, and say which file names which decision.

The expectations are worked by hand from decisions/decision-heads.md sections 1 and 4: a head is the YAML block
between two `---` lines at the top of the file, the title is the line `# <title>` after it, and the file name is
the id. A file without a head gives no row; a broken head is an error, never a missing head.
"""
from importlib.util import find_spec

import pytest

T = 1_800_000_000
GUIDE = "AGENTS.md"  # the folder guide of the fixture tree, which is no decision


class MissingDecisionHeadCapture(AssertionError):
    """loop/build_decision_capture.py does not read decision heads into std-decision rows."""


class MissingDecisionCitationCapture(AssertionError):
    """loop/build_decision_capture.py does not say which tracked file or red test names which decision."""


def write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")


SATURDAY = """---
decider: [loop, core]
decided_on: 2026-03-02
valid_from: 2026-04-01
valid_until: 2027-01-01
state: in_force
subject: opening-hours
---

# Open the reading room on Saturday

The room opens on Saturday too.
"""

PLAIN = "# A decision in running text\n\nIt was decided in 2025 and replaces nothing.\n"

SATURDAY_ROW = {
    "id": "saturday", "title": "Open the reading room on Saturday", "subject": "opening-hours",
    "decider": ["loop", "core"], "decided_on": "2026-03-02", "valid_from": "2026-04-01",
    "valid_from_day": 20260401, "valid_until": "2027-01-01", "valid_until_day": 20270101, "state": "in_force",
}

WEEKDAYS = """---
decider: [loop]
decided_on: 2025-02-12
valid_from: 2025-03-01
state: superseded
subject: opening-hours
---

# Open the reading room on weekdays
"""

SUNDAY = """---
decider: [owner]
state: proposed
supersedes: [saturday]
subject: opening-hours
---

# Open the reading room on Sunday
"""

BROKEN = {
    "quoted-day": SATURDAY.replace("decided_on: 2026-03-02", 'decided_on: "2026-03-02"'),
    "unknown-field": SATURDAY.replace("state: in_force", "state: in_force\nowner: [loop]"),
    "no-first-day": SATURDAY.replace("valid_from: 2026-04-01\nvalid_until: 2027-01-01\n", ""),
    "nobody-decided": SATURDAY.replace("decider: [loop, core]", "decider: []"),
    "unknown-state": SATURDAY.replace("state: in_force", "state: settled"),
    "unknown-decider": SATURDAY.replace("decider: [loop, core]", "decider: [board]"),
    "no-title": SATURDAY.replace("# Open the reading room on Saturday\n", "Open the reading room on Saturday\n"),
    "unclosed": SATURDAY.replace("---\n\n# Open", "\n# Open"),
}


def capture_module(missing):
    if find_spec("loop.build_decision_capture") is None:
        raise missing("loop/build_decision_capture.py does not exist")
    from loop import build_decision_capture

    return build_decision_capture


def test_decision_head_gives_one_decision_row(tmp_path):
    capture = capture_module(MissingDecisionHeadCapture)

    write(tmp_path / "one", {
        "decisions/saturday.md": SATURDAY, "decisions/plain.md": PLAIN, f"decisions/{GUIDE}": "# Working here\n",
    })
    assert capture.decision_rows(tmp_path / "one") == {
        "decision": [SATURDAY_ROW], "subject": [{"id": "opening-hours", "title": "opening-hours"}],
    }

    write(tmp_path / "chain", {
        "decisions/saturday.md": SATURDAY.replace("state: in_force", "state: in_force\nsupersedes: [weekdays]"),
        "decisions/weekdays.md": WEEKDAYS, "decisions/sunday.md": SUNDAY,
    })
    assert capture.decision_rows(tmp_path / "chain")["decision"] == [
        {**SATURDAY_ROW, "supersedes": ["weekdays"]},
        {"id": "sunday", "title": "Open the reading room on Sunday", "subject": "opening-hours",
         "decider": ["owner"], "state": "proposed", "supersedes": ["saturday"]},
        {"id": "weekdays", "title": "Open the reading room on weekdays", "subject": "opening-hours",
         "decider": ["loop"], "decided_on": "2025-02-12", "valid_from": "2025-03-01", "valid_from_day": 20250301,
         "state": "superseded"},
    ]

    for name, text in BROKEN.items():
        root = tmp_path / name
        write(root, {f"decisions/{name}.md": text, "decisions/plain.md": PLAIN})
        with pytest.raises(ValueError, match=f"decisions/{name}.md"):
            capture.decision_rows(root)


NEW = SATURDAY.replace("state: in_force", "state: in_force\nsupersedes: [weekdays]") + (
    "It replaces [the weekday hours](weekdays.md#why).\n"
)
OLD = WEEKDAYS + "\nThis is decisions/weekdays.md itself, and it names no other decision.\n"
TREE = {
    "decisions/saturday.md": NEW,
    "decisions/weekdays.md": OLD,
    "decisions/plain.md": PLAIN + "\nSee [the Saturday hours](saturday.md).\n",
    "handbook/hours.md": "Read [the old hours](../decisions/weekdays.md#why).\n",
    "handbook/other.md": "A link outside the decisions folder is not relative to it: [x](saturday.md).\n",
    "scripts/tool.py": "# decisions/plain.md has no head, so it has no row.\n",
    "loop/tests/test_hours.py": 'REASON = "extra: decisions/weekdays.md: section 1."\n',
    "handbook/picture.png": b"\x89PNG\r\n\x1a\n\x00\xff decisions/saturday.md",
    "notes.md": "An untracked file names decisions/saturday.md.\n",
}
TRACKED = sorted(set(TREE) - {"notes.md"})
RED = [
    {"id": "loop/tests/test_hours.py--test_waits", "reason": "extra: decisions/weekdays.md: section 1."},
    {"id": "loop/tests/test_hours.py--test_both",
     "reason": "extra: decisions/saturday.md and decisions/weekdays.md: both."},
    {"id": "loop/tests/test_hours.py--test_plain", "reason": "extra: decisions/plain.md: no head."},
    {"id": "loop/tests/test_hours.py--test_none", "reason": "extra: names no decision."},
]


@pytest.mark.xfail(
    strict=True,
    raises=MissingDecisionCitationCapture,
    reason=(
        "extra: decisions/decision-heads.md: section 4. Waits for loop/tests/test_build_decision_capture.py--"
        "test_decision_head_gives_one_decision_row (the same module). Add citation_rows(root, paths, red_tests, *, "
        "run, observed_at, source) to loop/build_decision_capture.py. It returns one build_citation_scan row "
        "{id, run, observed_at, source}, one build_decision_citation row {id, scan, path, decision} per tracked "
        "path whose text names a decision with a head (decisions/<id>.md anywhere, or ](<id>.md in a file under "
        "decisions/), never the decision's own file, and one build_red_citation row {id, scan, test, decision} "
        "per decision with a head that a red test's reason names. Only the given paths are read; a file that is "
        "not UTF-8 text names nothing. Ids are unique."
    ),
)
def test_decision_citations_name_each_file(tmp_path):
    capture = capture_module(MissingDecisionCitationCapture)
    if not hasattr(capture, "citation_rows"):
        raise MissingDecisionCitationCapture("loop/build_decision_capture.py has no citation_rows")

    write(tmp_path, TREE)
    rows = capture.citation_rows(tmp_path, TRACKED, RED, run="current", observed_at=T, source="tree")

    assert set(rows) == {"build_citation_scan", "build_decision_citation", "build_red_citation"}
    [scan] = rows["build_citation_scan"]
    assert {key: scan[key] for key in ("run", "observed_at", "source")} == {
        "run": "current", "observed_at": T, "source": "tree",
    }
    cited = rows["build_decision_citation"] + rows["build_red_citation"]
    ids = [scan["id"], *(row["id"] for row in cited)]
    assert all(isinstance(name, str) and name for name in ids) and len(set(ids)) == len(ids), ids
    assert {row["scan"] for row in cited} == {scan["id"]}
    assert sorted((row["path"], row["decision"]) for row in rows["build_decision_citation"]) == [
        ("decisions/plain.md", "saturday"),
        ("decisions/saturday.md", "weekdays"),
        ("handbook/hours.md", "weekdays"),
        ("loop/tests/test_hours.py", "weekdays"),
    ]
    assert sorted((row["test"], row["decision"]) for row in rows["build_red_citation"]) == [
        ("loop/tests/test_hours.py--test_both", "saturday"),
        ("loop/tests/test_hours.py--test_both", "weekdays"),
        ("loop/tests/test_hours.py--test_waits", "weekdays"),
    ]
