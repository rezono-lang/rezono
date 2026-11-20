"""Read decision file heads into std-decision rows."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

_DECIDERS = frozenset({"core", "language", "platform", "loop", "k8s-admission", "run", "owner"})
_STATES = frozenset({"proposed", "in_force", "superseded", "withdrawn"})
_FIELDS = frozenset({"decider", "decided_on", "valid_from", "valid_until", "state", "supersedes", "subject"})
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _split_head(text: str, rel: str) -> tuple[str, str] | None:
    """Return (yaml_text, title) when the file begins with a head, or None when it has no head."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{rel}: missing closing ---") from error
    if end + 2 >= len(lines) or lines[end + 1] != "" or not lines[end + 2].startswith("# "):
        raise ValueError(f"{rel}: expected an empty line and '# <title>' after head")
    title = lines[end + 2][2:].strip()
    if not title:
        raise ValueError(f"{rel}: empty title")
    return "\n".join(lines[1:end]), title


def _require_list(value: object, field: str, rel: str, *, allowed: frozenset[str] | None = None) -> list[str]:
    """Validate a non-empty list of strings, optionally restricted to an allowed vocabulary."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{rel}: {field} must be a non-empty list")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{rel}: {field} entries must be non-empty strings")
        if allowed is not None and item not in allowed:
            raise ValueError(f"{rel}: unknown {field} {item!r}")
        items.append(item)
    return items


def _require_day(value: object, field: str, rel: str) -> date:
    """Validate a plain unquoted YAML date within the schema bounds."""
    if type(value) is not date or not (1900 <= value.year <= 9999):
        raise ValueError(f"{rel}: {field} must be a plain YYYY-MM-DD date")
    return value


def _day_int(day: date) -> int:
    """Encode a calendar date as the whole number YYYYMMDD."""
    return day.year * 10000 + day.month * 100 + day.day


def _parse_row(path: Path) -> dict[str, Any] | None:
    """Parse one decision file into a Decision row, or None when it has no head."""
    rel = f"decisions/{path.name}"
    split = _split_head(path.read_text(encoding="utf-8"), rel)
    if split is None:
        return None
    raw_yaml, title = split
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as error:
        raise ValueError(f"{rel}: invalid YAML in head") from error
    if not isinstance(data, dict):
        raise ValueError(f"{rel}: head must be a YAML mapping")
    unknown = sorted(str(key) for key in set(data) - _FIELDS)
    if unknown:
        raise ValueError(f"{rel}: unknown field(s): {', '.join(unknown)}")

    state = data.get("state")
    if not isinstance(state, str) or state not in _STATES:
        raise ValueError(f"{rel}: invalid state {state!r}")
    decider = _require_list(data.get("decider"), "decider", rel, allowed=_DECIDERS)
    subject = data.get("subject")
    if not isinstance(subject, str) or not _SLUG.fullmatch(subject):
        raise ValueError(f"{rel}: invalid subject {subject!r}")

    if state != "proposed":
        if "decided_on" not in data:
            raise ValueError(f"{rel}: decided_on is required when state is {state}")
        if "valid_from" not in data:
            raise ValueError(f"{rel}: valid_from is required when state is {state}")

    row: dict[str, Any] = {
        "id": path.stem,
        "title": title,
        "subject": subject,
        "decider": decider,
        "state": state,
    }
    if "decided_on" in data:
        row["decided_on"] = _require_day(data["decided_on"], "decided_on", rel).isoformat()
    valid_from: date | None = None
    if "valid_from" in data:
        valid_from = _require_day(data["valid_from"], "valid_from", rel)
        row["valid_from"] = valid_from.isoformat()
        row["valid_from_day"] = _day_int(valid_from)
    if "valid_until" in data:
        if valid_from is None:
            raise ValueError(f"{rel}: valid_until requires valid_from")
        valid_until = _require_day(data["valid_until"], "valid_until", rel)
        if valid_until <= valid_from:
            raise ValueError(f"{rel}: valid_until must come after valid_from")
        row["valid_until"] = valid_until.isoformat()
        row["valid_until_day"] = _day_int(valid_until)
    if "supersedes" in data:
        row["supersedes"] = _require_list(data["supersedes"], "supersedes", rel)
    return row


def decision_rows(root: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Read decision heads under ``root/decisions/*.md`` (except AGENTS.md) into decision and subject rows."""
    decisions_dir = Path(root) / "decisions"
    if not decisions_dir.is_dir():
        return {"decision": [], "subject": []}

    decisions: list[dict[str, Any]] = []
    subjects: set[str] = set()
    for path in sorted(decisions_dir.glob("*.md"), key=lambda item: item.stem):
        if path.name == "AGENTS.md" or not path.is_file():
            continue
        row = _parse_row(path)
        if row is not None:
            decisions.append(row)
            subjects.add(row["subject"])
    return {
        "decision": decisions,
        "subject": [{"id": slug, "title": slug} for slug in sorted(subjects)],
    }


def _named(text: str, ids: list[str], *, in_decisions: bool) -> list[str]:
    """Return the decision ids a text names, in id order."""
    return [
        ident for ident in ids
        if f"decisions/{ident}.md" in text or (in_decisions and f"]({ident}.md" in text)
    ]


def citation_rows(
    root: str | Path,
    paths: list[str],
    red_tests: list[dict[str, Any]],
    *,
    run: str,
    observed_at: int,
    source: str,
) -> dict[str, list[dict[str, Any]]]:
    """Say which tracked file and which red test names which decision with a head (decision-heads.md section 4)."""
    base = Path(root)
    ids = [row["id"] for row in decision_rows(base)["decision"]]
    scan = f"citations@{run}@{observed_at}"
    files: list[dict[str, Any]] = []
    for rel in sorted(set(paths)):
        try:
            text = (base / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        folder, _, name = rel.rpartition("/")
        own = name[:-3] if folder == "decisions" and name.endswith(".md") else None
        for ident in _named(text, ids, in_decisions=folder == "decisions"):
            if ident != own:
                files.append({"id": f"{scan}@{rel}@{ident}", "scan": scan, "path": rel, "decision": ident})
    reds: list[dict[str, Any]] = []
    for test in sorted({str(item["id"]): str(item.get("reason", "")) for item in red_tests}.items()):
        for ident in _named(test[1], ids, in_decisions=False):
            reds.append({"id": f"{scan}@{test[0]}@{ident}", "scan": scan, "test": test[0], "decision": ident})
    return {
        "build_citation_scan": [{"id": scan, "run": run, "observed_at": observed_at, "source": source}],
        "build_decision_citation": files,
        "build_red_citation": reds,
    }
