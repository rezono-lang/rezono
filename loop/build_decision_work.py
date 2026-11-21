"""Thin coordinator reader over checker-verified decision-status publications.

Projects published ``build_decision_open``, ``build_decision_open_test``,
``build_decision_untested`` and ``build_decision_done`` relations into worker
and planner tasks with explicit ``decisions/<id>.md -> <test>`` reason chains.
Never accepts or invokes a Python fallback: any missing, unverified or
incomplete publication fails closed with ``verified=False`` and keeps all
known and headless decisions ``unknown`` (never ``done``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import datetime
from pathlib import Path
import re
from typing import Any

_REQUIRED_CHECKS = frozenset({"rezono:proofs", "rezono:schema"})
_REQUIRED_RELATIONS = {
    "build_decision_open": 2,
    "build_decision_open_test": 3,
    "build_decision_untested": 2,
    "build_decision_done": 2,
}

_DECISION_DECIDERS = frozenset({"core", "language", "platform", "loop", "k8s-admission", "run", "owner"})
_DECISION_STATES = frozenset({"proposed", "in_force", "superseded", "withdrawn"})
_DECISION_FIELDS = frozenset({
    "decider",
    "decided_on",
    "valid_from",
    "valid_until",
    "state",
    "supersedes",
    "subject",
})
_DECISION_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DECISION_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_FULL_CITATION = re.compile(r"(?<![A-Za-z0-9_-])decisions/([A-Za-z0-9_-]+)\.md(?=$|[^A-Za-z0-9_-])")
_RELATIVE_CITATION = re.compile(r"\]\((?:\./)?([A-Za-z0-9_-]+)\.md(?=$|[^A-Za-z0-9_-])")


def _verified_manifest(manifest: Mapping[str, Any]) -> bool:
    """Return whether rezono:proofs and rezono:schema are green with no non-green checks."""
    checks = manifest.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
        return False
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, Mapping) or check.get("status") != "green":
            return False
        name = check.get("name")
        if isinstance(name, str) and name:
            seen.add(name)
    return _REQUIRED_CHECKS <= seen


def _row_key(row: object, size: int, run: str) -> tuple[str, ...]:
    """Extract a validated publication row key for ``run`` or raise ``ValueError``."""
    key = row.get("key") if isinstance(row, Mapping) else None
    if not isinstance(key, (list, tuple)) or len(key) != size:
        raise ValueError(f"malformed publication row: {row!r}")
    if not all(isinstance(part, str) and part for part in key):
        raise ValueError(f"malformed publication row: {row!r}")
    if key[0] != run:
        raise ValueError(f"publication row belongs to another run: {key[0]!r}")
    return tuple(key)


def _normalize_decision_id(value: str) -> str:
    """Normalize a decision id or ``decisions/<id>.md`` path to its bare decision id."""
    if not isinstance(value, str):
        raise ValueError(f"decision identifier must be a string, got {value!r}")
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("decisions/"):
        normalized = normalized[len("decisions/"):]
    if normalized.endswith(".md"):
        normalized = normalized[:-3]
    if not normalized or "/" in normalized:
        raise ValueError(f"invalid decision identifier: {value!r}")
    return normalized


def _unverified_result(run: str, unknown: list[str]) -> dict[str, Any]:
    return {
        "run": run,
        "verified": False,
        "worker_tasks": [],
        "planner_tasks": [],
        "open": [],
        "untested": [],
        "done": [],
        "unknown": unknown,
        "progress": {
            "open": 0,
            "untested": 0,
            "done": 0,
            "unknown": len(unknown),
        },
    }


def read_decision_work(
    *,
    run: str,
    manifest: Mapping[str, Any] | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    headless_decisions: Iterable[str] = (),
    known_decisions: Iterable[str] = (),
) -> dict[str, Any]:
    """Project verified decision-status relations into worker and planner tasks.

    When ``manifest`` or ``rows`` is missing, unverified or incomplete, fails
    closed with ``verified=False``, empty task lists, empty ``done`` and every
    known or headless decision placed into ``unknown``.
    """
    if not isinstance(run, str) or not run:
        raise ValueError(f"run must be a non-empty string, got {run!r}")

    headless_ids = {_normalize_decision_id(item) for item in headless_decisions}
    known_ids = {_normalize_decision_id(item) for item in known_decisions}

    if manifest is None or rows is None:
        return _unverified_result(run, sorted(known_ids | headless_ids))
    if not isinstance(manifest, Mapping) or not _verified_manifest(manifest):
        return _unverified_result(run, sorted(known_ids | headless_ids))
    if not isinstance(rows, Mapping) or any(
        not isinstance(rows.get(name), Sequence) or isinstance(rows.get(name), (str, bytes))
        for name in _REQUIRED_RELATIONS
    ):
        return _unverified_result(run, sorted(known_ids | headless_ids))

    open_ids = {_row_key(row, 2, run)[1] for row in rows["build_decision_open"]}
    open_tests = sorted({_row_key(row, 3, run)[1:] for row in rows["build_decision_open_test"]})
    untested_ids = {_row_key(row, 2, run)[1] for row in rows["build_decision_untested"]}
    done_ids = {_row_key(row, 2, run)[1] for row in rows["build_decision_done"]}

    open_test_decisions = {decision for decision, _ in open_tests}
    missing_witness = sorted(open_ids - open_test_decisions)
    if missing_witness:
        raise ValueError(f"open decision(s) missing build_decision_open_test witness: {', '.join(missing_witness)}")
    orphan_witness = sorted(open_test_decisions - open_ids)
    if orphan_witness:
        raise ValueError(f"build_decision_open_test edge(s) without build_decision_open row: {', '.join(orphan_witness)}")

    overlap = sorted((open_ids & untested_ids) | (open_ids & done_ids) | (untested_ids & done_ids))
    if overlap:
        raise ValueError(f"decision(s) appear in multiple status relations: {', '.join(overlap)}")

    headless_classified = sorted((open_ids | untested_ids | done_ids) & headless_ids)
    if headless_classified:
        raise ValueError(
            f"headless decision(s) cannot appear in open, untested or done relations: {', '.join(headless_classified)}"
        )

    worker_tasks = [
        {
            "role": "worker",
            "status": "open",
            "decision": decision,
            "decision_path": f"decisions/{decision}.md",
            "test": test,
            "reason": f"decisions/{decision}.md -> {test}",
        }
        for decision, test in open_tests
    ]
    planner_tasks = [
        {
            "role": "planner",
            "status": "untested",
            "decision": decision,
            "decision_path": f"decisions/{decision}.md",
            "test": None,
            "reason": f"decisions/{decision}.md -> untested",
        }
        for decision in sorted(untested_ids)
    ]

    open_list = sorted(open_ids)
    untested_list = sorted(untested_ids)
    done_list = sorted(done_ids)
    unknown_list = sorted((known_ids - open_ids - untested_ids - done_ids) | headless_ids)

    return {
        "run": run,
        "verified": True,
        "worker_tasks": worker_tasks,
        "planner_tasks": planner_tasks,
        "open": open_list,
        "untested": untested_list,
        "done": done_list,
        "unknown": unknown_list,
        "progress": {
            "open": len(open_list),
            "untested": len(untested_list),
            "done": len(done_list),
            "unknown": len(unknown_list),
        },
    }


def _parse_flow_list(raw: str) -> list[str] | None:
    """Parse a non-empty YAML flow list ``[a, b]`` using only the standard library, or None."""
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return None
    inner = raw[1:-1].strip()
    if not inner:
        return None
    items: list[str] = []
    for part in inner.split(","):
        item = part.strip()
        if not item:
            return None
        if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"}:
            item = item[1:-1]
        if not item or any(ch in item for ch in "[]{}:#"):
            return None
        items.append(item)
    return items


def _parse_plain_date(raw: str) -> datetime.date | None:
    """Parse an unquoted YAML ``YYYY-MM-DD`` date within schema bounds, or None."""
    match = _DECISION_DATE.fullmatch(raw.strip())
    if not match:
        return None
    try:
        day = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return day if 1900 <= day.year <= 9999 else None


def _has_valid_decision_head(data: bytes) -> bool:
    """Return whether ``data`` begins with a valid YAML decision head (decision-heads.md section 1)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return False
    try:
        close = lines.index("---", 1)
    except ValueError:
        return False
    if (
        close + 2 >= len(lines)
        or lines[close + 1] != ""
        or not lines[close + 2].startswith("# ")
        or not lines[close + 2][2:].strip()
    ):
        return False
    fields: dict[str, str] = {}
    for line in lines[1:close]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace() or ":" not in line:
            return False
        key, _, val = line.partition(":")
        key = key.strip()
        if key not in _DECISION_FIELDS or key in fields:
            return False
        fields[key] = val.strip()
    if not {"decider", "state", "subject"} <= set(fields):
        return False
    state = fields["state"]
    if state not in _DECISION_STATES:
        return False
    decider = _parse_flow_list(fields["decider"])
    if not decider or not set(decider) <= _DECISION_DECIDERS:
        return False
    if not _DECISION_SLUG.fullmatch(fields["subject"]):
        return False
    if state != "proposed" and not {"decided_on", "valid_from"} <= set(fields):
        return False
    days: dict[str, datetime.date] = {}
    for name in ("decided_on", "valid_from", "valid_until"):
        if name in fields:
            parsed = _parse_plain_date(fields[name])
            if parsed is None:
                return False
            days[name] = parsed
    if "valid_until" in days and not ("valid_from" in days and days["valid_from"] < days["valid_until"]):
        return False
    if "supersedes" in fields:
        supersedes = _parse_flow_list(fields["supersedes"])
        if not supersedes or not all(_DECISION_SLUG.fullmatch(item) for item in supersedes):
            return False
    return True


def prioritize_headless_decisions(
    root: str | Path,
    budget_paths: Iterable[str],
    red_tests: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Order headless-decision budget paths by red-test and headed-decision citation priority.

    Tiers (from highest to lowest priority):
    1. ``red-cited``: cited in the reason of at least one red test;
    2. ``headed-cited``: cited by at least one decision with a valid YAML head;
    3. ``other``: all remaining budget entries, ordered alphabetically by path.
    """
    decision_ids: dict[str, str] = {}
    for raw_path in budget_paths:
        decision_id = _normalize_decision_id(raw_path)
        decision_ids[decision_id] = f"decisions/{decision_id}.md"

    red_by_decision: dict[str, set[str]] = {ident: set() for ident in decision_ids}
    headed_by_decision: dict[str, set[str]] = {ident: set() for ident in decision_ids}

    for item in red_tests:
        if not isinstance(item, Mapping):
            raise ValueError(f"red test entry must be a mapping, got {item!r}")
        test_id = item.get("id")
        if not isinstance(test_id, str) or not test_id:
            raise ValueError(f"red test entry missing non-empty id: {item!r}")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason:
            continue
        for cited in _FULL_CITATION.findall(reason):
            if cited in red_by_decision:
                red_by_decision[cited].add(test_id)

    decisions_dir = Path(root) / "decisions"
    if decisions_dir.is_dir():
        for path in sorted(decisions_dir.glob("*.md"), key=lambda item: item.stem):
            if path.name == "AGENTS.md" or not path.is_file():
                continue
            raw = path.read_bytes()
            if not _has_valid_decision_head(raw):
                continue
            text = raw.decode("utf-8")
            own = path.stem
            cited_ids = set(_FULL_CITATION.findall(text)) | set(_RELATIVE_CITATION.findall(text))
            for cited in cited_ids:
                if cited != own and cited in headed_by_decision:
                    headed_by_decision[cited].add(own)

    ranked: list[tuple[tuple[int, int, int, str], dict[str, Any]]] = []
    for decision_id, rel_path in decision_ids.items():
        reds = sorted(red_by_decision[decision_id])
        headeds = sorted(headed_by_decision[decision_id])
        if reds:
            tier = "red-cited"
            tier_rank = 0
        elif headeds:
            tier = "headed-cited"
            tier_rank = 1
        else:
            tier = "other"
            tier_rank = 2
        entry = {
            "path": rel_path,
            "decision": decision_id,
            "tier": tier,
            "red_tests": reds,
            "headed_decisions": headeds,
        }
        ranked.append(((tier_rank, -len(reds), -len(headeds), rel_path), entry))

    ranked.sort(key=lambda pair: pair[0])
    return [entry for _, entry in ranked]
